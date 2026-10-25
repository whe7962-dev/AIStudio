"""确定性电商闭环流水线（demo 可离线跑通）：新建 SKU → 上传实拍 → 抠图/质检 →
锚点 → 批量草稿 → 评分 → 后处理导出。

用途：无真实模型/无桌面 App 时验证「可独立运行」；真实 LLM 循环接入后由模型驱动同一条链路。
"""

from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

from .plan import TodoList
from .settings import Settings, get_settings
from .workspace import Workspace


def _make_sample_images(dest: Path, n: int = 3) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        img = Image.new("RGB", (512, 512), (200 + i * 12, 175 + i * 8, 160))
        draw = ImageDraw.Draw(img)
        draw.rectangle([128, 128, 384, 384], fill=(250, 250, 250), outline=(40, 40, 40), width=4)
        draw.text((10, 10), f"sample_{i}", fill=(20, 20, 20))
        p = dest / f"sample_{i}.png"
        img.save(p, format="PNG")
        paths.append(str(p))
    return paths


def _wait_job(ws: Workspace, project_id: str, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = ws.job_status(project_id, job_id)
        if status["status"] in {"completed", "degraded", "failed", "cancelled"}:
            return status
        time.sleep(0.1)
    raise TimeoutError(f"job {job_id} 超时未完成")


def run_ecommerce_demo(settings: Settings | None = None, workspace: Workspace | None = None,
                       output_dir: Path | None = None) -> dict:
    settings = settings or get_settings()
    ws = workspace or Workspace(settings)
    ctx = ws.create_project()
    project_id = ctx.project.project_id
    graph = ctx.project

    tmp = Path(settings.data_dir) / "tmp" / project_id
    sample_paths = _make_sample_images(tmp)
    out_dir = output_dir or (Path(settings.data_dir) / "exports" / project_id)

    todo = TodoList()

    # 1) 上传实拍 → 抠图/质检（E1）
    t_ingest = todo.add("ingest_and_qa_photos")
    todo.start(t_ingest.id)
    ingest_result = ws.dispatcher.dispatch(
        "ingest_and_qa_photos",
        {"image_paths": sample_paths, "sku_id": "sku_demo"},
        ctx,
    )
    todo.done(t_ingest.id)

    # 2) 一致性锚点（P2）
    t_anchor = todo.add("build_consistency_anchor")
    todo.start(t_anchor.id)
    photo_ids = [r["source_asset_id"] for r in ingest_result["items"]
                 if r.get("qa", {}).get("ok")]
    anchor_result = ws.dispatcher.dispatch(
        "build_consistency_anchor",
        {"photo_ids": photo_ids, "product_understanding": "demo 商品"},
        ctx,
    )
    todo.done(t_anchor.id)

    # 3) 批量草稿（P4，走单执行道 + 优先级队列）
    t_gen = todo.add("generate_image")
    todo.start(t_gen.id)
    gen_job = ws.submit(
        project_id,
        "generate_image",
        {"mode": "draft", "prompt": "白底电商主图，商品居中，简洁干净",
         "anchor_id": anchor_result["anchor_asset_id"], "seed": 42, "count": 4,
         "width": 1024, "height": 1024},
        priority="draft",
    )
    gen_status = _wait_job(ws, project_id, gen_job["job_id"])
    if gen_status["status"] != "completed":
        raise RuntimeError(f"生成失败: {gen_status}")
    gen_result = ws.job_result(gen_job["job_id"])
    todo.done(t_gen.id)

    # 4) 一致性评分（E3）
    t_score = todo.add("score_fidelity_and_batch_qa")
    todo.start(t_score.id)
    score_result = ws.dispatcher.dispatch(
        "score_fidelity_and_batch_qa",
        {"asset_ids": gen_result["asset_ids"], "anchor_id": anchor_result["anchor_asset_id"]},
        ctx,
    )
    todo.done(t_score.id)

    # 5) 后处理导出（P6，需用户确认 → demo 显式 confirmed=True）
    t_export = todo.add("postprocess_and_package")
    todo.start(t_export.id)
    export_result = ws.dispatcher.dispatch(
        "postprocess_and_package",
        {"asset_id": gen_result["asset_ids"][0], "channels": ["douyin"],
         "output_dir": str(out_dir), "sku_id": "sku_demo"},
        ctx,
        confirmed=True,
    )
    todo.done(t_export.id)

    graph.save(ctx.workspace / "project.json")
    return {
        "project_id": project_id,
        "package_dir": export_result["package_dir"],
        "files": export_result["files"],
        "batch_consistency": score_result["batch_consistency"],
        "todo": todo.summary(),
        "metrics": ws.metrics.snapshot(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run_ecommerce_demo(), ensure_ascii=False, indent=2))
