"""最小商品图 demo（Phase 1 场景图版，异步任务）。

流程：上传参考图 → 提交生成任务（返回 job_id）→ 前端轮询进度 →
每张图完成即显示 → 取消保留已完成图 → 失败可单张重试 → 落盘 + 导出。

- 参考图真正参与生成：Seedream flash 图生图（image 走 data URL，支持 size / strength）。
- 每张图独立状态 success / failed；不静默回退。
- 本地抠图+合成仅用于「未配置 seedream key」的离线兜底。
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFilter, ImageStat

from .settings import ROOT_DIR

logger = logging.getLogger("aiside.demo")
router = APIRouter()

MAX_COUNT = 8
MAX_PARALLEL = 2
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ACTIVE_STATES = {"generating", "canceling"}

_SCENE_BG = {
    "studio": ((247, 248, 250), (230, 233, 238)),
    "home": ((216, 196, 160), (184, 160, 124)),
    "outdoor": ((188, 214, 160), (150, 190, 130)),
    "festival": ((224, 176, 160), (200, 150, 132)),
    "minimal": ((240, 240, 240), (228, 228, 228)),
    "street": ((160, 184, 200), (130, 156, 174)),
}

_VARIANTS = [
    {"scale": 0.62, "dy": 0.02},
    {"scale": 0.74, "dy": 0.00},
    {"scale": 0.52, "dy": 0.04},
    {"scale": 0.62, "dy": 0.09},
]

_REMBG_SESSION = None
_REMBG_LOCK = threading.Lock()

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


# ---------- 配置 / 预设 ----------
def _load_presets() -> list[dict]:
    path = ROOT_DIR / "config" / "presets.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("presets", [])
    return []


def _detect_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _mime_to_ext(mime: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(mime, "bin")


def _to_data_url(data: bytes) -> str:
    return f"data:{_detect_mime(data)};base64,{base64.b64encode(data).decode('ascii')}"


def _hex_to_rgb(color: str) -> tuple:
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _preset_thumb(preset: dict) -> str:
    rgb = _hex_to_rgb(preset.get("color", "#e8e8ee"))
    img = _gradient((96, 96), rgb, tuple(max(0, c - 24) for c in rgb))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return _to_data_url(buf.getvalue())


# ---------- 本地兜底：抠图 + 合成 ----------
def _get_rembg_session():
    global _REMBG_SESSION
    if _REMBG_SESSION is None:
        from rembg import new_session
        _REMBG_SESSION = new_session("u2netp")
    return _REMBG_SESSION


def _cutout(raw: bytes) -> bytes:
    from rembg import remove
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    with _REMBG_LOCK:
        out = remove(img, session=_get_rembg_session())
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    w, h = size
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        d.line([(0, y), (w, y)], fill=color)
    return img


def _composite(cutout: Image.Image, scene_id: str, size: tuple, variant: dict) -> Image.Image:
    w, h = size
    top, bottom = _SCENE_BG.get(scene_id, _SCENE_BG["studio"])
    bg = _gradient(size, top, bottom).convert("RGBA")

    scale = variant["scale"]
    cw, ch = cutout.size
    target_w = int(w * scale)
    target_h = int(ch * target_w / max(1, cw))
    if target_h > int(h * 0.8):
        target_h = int(h * 0.8)
        target_w = int(cw * target_h / max(1, ch))
    cup = cutout.resize((target_w, target_h), Image.LANCZOS)

    x = (w - target_w) // 2
    y = int((h - target_h) / 2 + h * variant["dy"])

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sw = int(target_w * 0.85)
    sh = int(target_h * 0.14)
    sx = x + (target_w - sw) // 2
    sy = y + target_h - sh // 2
    sd.ellipse([sx, sy, sx + sw, sy + sh], fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))

    out = Image.alpha_composite(bg, shadow)
    out.paste(cup, (x, y), cup)
    return out.convert("RGB")


def _composite_from_raw(raw: bytes, scene_id: str, index: int, size: tuple) -> bytes:
    cutout = Image.open(io.BytesIO(_cutout(raw))).convert("RGBA")
    img = _composite(cutout, scene_id, size, _VARIANTS[index % len(_VARIANTS)])
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except Exception:
        return 1024, 1024


def _blur_score(img: Image.Image) -> float:
    """拉普拉斯方差，越大越清晰（近似，无 numpy）。"""
    gray = img.convert("L").resize((256, 256))
    lap = gray.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=0))
    return ImageStat.Stat(lap).var[0]


def _qa_image(raw: bytes, index: int) -> dict:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
        w, h = img.size
    except Exception:
        return {"index": index, "ok": False, "warnings": ["格式不支持（仅 jpg/png/webp）"]}
    warnings = []
    if len(raw) > 10 * 1024 * 1024:
        warnings.append("文件过大（>10MB）")
    if w < 512 or h < 512:
        warnings.append("分辨率过低（建议 ≥512×512）")
    blur = _blur_score(img)
    if blur < 50:
        warnings.append("可能模糊，建议换更清晰的正面图")
    return {"index": index, "ok": not warnings, "width": w, "height": h,
            "size_kb": round(len(raw) / 1024, 1), "blur": round(blur, 1),
            "warnings": warnings}


# ---------- 单张生成（供同步函数与异步 job 共用）----------
def _generate_one_scene(provider, raw: bytes, prompt: str, scene_id: str,
                        index: int, seed: int, reference_strength: float,
                        size: str):
    if getattr(provider, "name", "") == "seedream":
        try:
            img = provider.inpaint(image_data=raw, prompt=prompt, seed=seed,
                                   strength=reference_strength, size=size)
            return index, {"id": f"img_{index}", "status": "success",
                           "source": "seedream", "data_url": _to_data_url(img.data),
                           "strength": reference_strength, "seed": seed,
                           "created_at": time.time()}
        except Exception as exc:  # noqa: BLE001 - 失败可重试
            logger.warning("生图失败（可重试）index=%s: %s", index, exc)
            return index, {"id": f"img_{index}", "status": "failed",
                           "source": "seedream", "error": str(exc)[:200],
                           "strength": reference_strength, "seed": seed,
                           "created_at": time.time()}
    w, h = _parse_size(size)
    data = _composite_from_raw(raw, scene_id, index, (w, h))
    return index, {"id": f"img_{index}", "status": "success",
                   "source": "local", "data_url": _to_data_url(data),
                   "strength": reference_strength, "seed": seed,
                   "created_at": time.time()}


def generate_scene_images(provider, raw: bytes, prompt: str, scene_id: str,
                          count: int, reference_strength: float = 0.75,
                          lock_product: bool = True,
                          size: str = "1024x1024") -> dict:
    """同步版（供测试用）：并行生成，每张独立 success/failed。"""
    count = max(1, min(int(count), MAX_COUNT))
    reference_strength = max(0.0, min(1.0, float(reference_strength)))
    with ThreadPoolExecutor(max_workers=count) as ex:
        futures = [ex.submit(_generate_one_scene, provider, raw, prompt, scene_id,
                             i, 1000 + i, reference_strength, size)
                   for i in range(count)]
        ordered = [f.result() for f in futures]
    ordered.sort(key=lambda item: item[0])
    images = [item[1] for item in ordered]
    return {"images": images, "provider": getattr(provider, "name", "stub"),
            "count": count, "reference_strength": reference_strength,
            "lock_product": lock_product, "size": size, "prompt": prompt,
            "failed": sum(1 for i in images if i["status"] == "failed")}


# ---------- 异步任务 / 持久化 ----------
def _final_status(job: dict) -> str:
    if job["cancel"].is_set():
        return "canceled"
    successes = sum(bool(x and x["status"] == "success") for x in job["images"])
    if successes == len(job["images"]):
        return "success"
    return "partial" if successes else "failed"


def _job_dir(settings, job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{10}", job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return Path(settings.data_dir) / "demo" / job_id


def _safe_name(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w-]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return value[:80] or fallback


def _image_filename(job: dict, index: int, img: dict) -> str:
    if img.get("filename"):
        return Path(img["filename"]).name
    p = job["params"]
    sku = _safe_name(p.get("sku", ""), "sku")
    scene = _safe_name(p.get("scene", ""), "studio")
    w, h = _parse_size(p.get("size", "1024x1024"))
    ext = _mime_to_ext(img["data_url"].split(";")[0].split(":")[1])
    return f"{sku}_{scene}_{index + 1}_{w}x{h}.{ext}"


def _atomic_write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def _save_image(settings, job: dict, index: int, img: dict) -> None:
    out_dir = _job_dir(settings, job["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _image_filename(job, index, img)
    _atomic_write(out_dir / name, base64.b64decode(img["data_url"].split(",", 1)[1]))
    img["filename"] = name


def _save_manifest(settings, job: dict) -> None:
    # Caller holds job lock: publish a coherent snapshot after each finished image.
    out_dir = _job_dir(settings, job["id"])
    out_dir.mkdir(parents=True, exist_ok=True)
    p = job["params"]
    files = [_image_filename(job, i, img) for i, img in enumerate(job["images"])
             if img and img["status"] == "success"]
    manifest = {
        "schema_version": 2, "job_id": job["id"], "status": job["status"],
        "provider": job["provider_name"], "model": job.get("model", job["provider_name"]),
        "created_at": job["created_at"], "params": p,
        "sku": p.get("sku", "sku"), "prompt": p.get("prompt", ""),
        "negative_prompt": p.get("negative_prompt", ""),
        "reference_strength": p.get("strength"), "size": p.get("size"),
        "next_seed": job["next_seed"], "count": len(job["images"]), "files": files,
        "images": [{k: v for k, v in img.items() if k != "data_url"} if img else None
                   for img in job["images"]],
    }
    _atomic_write(out_dir / "manifest.json",
                  json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["filename", "seed", "prompt", "model", "size", "created_at"])
    for i, img in enumerate(job["images"]):
        if img and img["status"] == "success":
            writer.writerow([_image_filename(job, i, img), img.get("seed", ""),
                             p.get("prompt", ""), job.get("model", job["provider_name"]),
                             p.get("size", ""), img.get("created_at", "")])
    _atomic_write(out_dir / "manifest.csv", output.getvalue().encode("utf-8-sig"))


def _run_job(settings, job: dict, seeds: dict[int, int]) -> None:
    p = job["params"]

    def work(i: int, seed: int):
        with job["lock"]:
            if job["cancel"].is_set():
                return i, {"id": f"img_{i}", "status": "canceled", "seed": seed}
        try:
            return _generate_one_scene(job["provider"], job["raw"], p["prompt"], p["scene"],
                                       i, seed, p["strength"], p["size"])
        except Exception as exc:
            return i, {"id": f"img_{i}", "status": "failed", "seed": seed,
                       "error": str(exc)[:200], "created_at": time.time()}

    try:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(seeds))) as ex:
            futures = [ex.submit(work, i, seed) for i, seed in seeds.items()]
            for fut in as_completed(futures):
                i, res = fut.result()
                with job["lock"]:
                    if res["status"] == "success":
                        _save_image(settings, job, i, res)
                    job["images"][i] = res
                    _save_manifest(settings, job)
    except Exception:
        logger.exception("任务保存失败 job=%s", job["id"])
        with job["lock"]:
            for i in seeds:
                if job["images"][i] is None:
                    job["images"][i] = {"id": f"img_{i}", "status": "failed",
                                         "seed": seeds[i], "error": "任务处理失败，请检查磁盘空间后重试"}
    finally:
        with job["lock"]:
            job["status"] = _final_status(job)
            _save_manifest(settings, job)


def _new_job(settings, provider, raw: bytes, params: dict) -> dict:
    job_id = uuid.uuid4().hex[:10]
    job = {
        "id": job_id, "provider": provider, "raw": raw,
        "provider_name": getattr(provider, "name", "stub"),
        "model": getattr(provider, "model_draft", getattr(provider, "name", "stub")),
        "params": params, "status": "generating", "lock": threading.RLock(),
        "images": [None] * params["count"], "next_seed": params["seed_base"] + params["count"],
        "cancel": threading.Event(), "created_at": time.time(),
        "data_root": str(Path(settings.data_dir).resolve()),
    }
    out_dir = _job_dir(settings, job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(out_dir / "reference.bin", raw)
    _save_manifest(settings, job)
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    seeds = {i: params["seed_base"] + i for i in range(params["count"])}
    threading.Thread(target=_run_job, args=(settings, job, seeds), daemon=True).start()
    return job


def _get_job(job_id: str, request: Request) -> dict:
    settings = request.app.state.settings
    out_dir = _job_dir(settings, job_id)
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None and job.get("data_root") == str(Path(settings.data_dir).resolve()):
            return job
        path = out_dir / "manifest.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="任务不存在")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            legacy_files = [name for name in manifest.get("files", [])
                            if name not in {"cutout.png", "reference.bin"}]
            stored_images = manifest.get("images")
            if stored_images is None:
                stored_images = [{"id": f"img_{i}", "status": "success", "filename": name,
                                  "source": manifest.get("provider", "unknown")}
                                 for i, name in enumerate(legacy_files)]
            params = manifest.get("params") or {
                "sku": manifest.get("sku", "sku"), "prompt": manifest.get("prompt", ""),
                "scene": "studio", "size": manifest.get("size", "1024x1024"),
                "strength": manifest.get("reference_strength", 0.75),
                "count": manifest.get("count", len(stored_images)), "seed_base": 1000,
            }
            images = [None] * int(params["count"])
            file_iter = iter(legacy_files)
            for index, img in enumerate(stored_images):
                if img is None:
                    continue
                i = int(img.get("id", f"img_{index}").split("_")[-1])
                if not 0 <= i < len(images):
                    continue
                if img["status"] == "success":
                    filename = img.get("filename") or next(file_iter, "")
                    if not filename or Path(filename).name != filename or not (out_dir / filename).is_file():
                        img.update(status="failed", error="图片文件缺失，可重新生成")
                    else:
                        img["filename"] = filename
                        img["data_url"] = _to_data_url((out_dir / filename).read_bytes())
                images[i] = img
            interrupted = manifest.get("status") in ACTIVE_STATES
            for i, img in enumerate(images):
                if img is None:
                    images[i] = {"id": f"img_{i}", "status": "interrupted", "error": "任务已中断，可重试"}
            reference = out_dir / "reference.bin"
            job = {
                "id": job_id, "provider": request.app.state.provider,
                "provider_name": manifest.get("provider", "unknown"),
                "model": manifest.get("model", manifest.get("provider", "unknown")),
                "raw": reference.read_bytes() if reference.is_file() else None,
                "params": params, "images": images, "lock": threading.RLock(),
                "cancel": threading.Event(), "created_at": manifest.get("created_at", path.stat().st_mtime),
                "next_seed": manifest.get("next_seed", max((x.get("seed", 0) or 0 for x in images), default=1000) + 1),
                "data_root": str(Path(settings.data_dir).resolve()),
            }
            job["status"] = "interrupted" if interrupted else manifest.get("status", _final_status(job))
            _JOBS[job_id] = job
            return job
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise HTTPException(status_code=409, detail="历史任务文件无法读取") from exc


def _job_summary(job: dict) -> dict:
    return {"job_id": job["id"], "status": job["status"], "count": len(job["images"]),
            "completed": sum(x is not None for x in job["images"]),
            "succeeded": sum(bool(x and x["status"] == "success") for x in job["images"]),
            "failed": sum(bool(x and x["status"] == "failed") for x in job["images"]),
            "created_at": job["created_at"], "sku": job["params"].get("sku", "sku")}


class RetryBody(BaseModel):
    indices: list[int] | None = None
    seed_mode: Literal["new", "same"] = "new"


# ---------- 路由 ----------
@router.get("/api/demo/presets")
def presets() -> dict:
    items = []
    for p in _load_presets():
        items.append({"id": p["id"], "name": p["name"],
                      "fragment": f"{p.get('bg', '')}，{p.get('light', '')}，{p.get('compose', '')}",
                      "thumb": _preset_thumb(p)})
    return {"presets": items}


@router.get("/api/demo/scenes")
def scenes() -> dict:
    return presets()


@router.post("/api/demo/generate")
async def generate(request: Request,
                   images: list[UploadFile] = File(...),
                   prompt: str = Form(...),
                   scene: str = Form("studio"),
                   count: int = Form(4),
                   reference_strength: float = Form(0.75),
                   lock_product: bool = Form(True),
                   negative_prompt: str = Form(""),
                   size: str = Form("1024x1024"),
                   sku: str = Form("sku"),
                   primary_index: int = Form(0),
                   seed_base: int = Form(1000)) -> dict:
    if not 1 <= len(images) <= 5:
        raise HTTPException(status_code=400, detail="请上传 1–5 张参考图")
    if size not in {"1024x1024", "1536x1536", "2048x2048"}:
        raise HTTPException(status_code=400, detail="请选择支持的方图尺寸")
    if count not in {1, 2, 4, 8}:
        raise HTTPException(status_code=400, detail="生成数量必须为 1、2、4 或 8")
    if not 0 <= primary_index < len(images):
        raise HTTPException(status_code=400, detail="请选择有效的主参考图")
    if not 0 <= seed_base <= 2147483647 - MAX_COUNT:
        raise HTTPException(status_code=400, detail="种子超出支持范围")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="请填写生成提示词")
    raws = []
    for im in images:
        raw = await im.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="每张参考图不能超过 10MB")
        if _detect_mime(raw) not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=400, detail="仅支持 JPG、PNG、WebP 图片")
        try:
            Image.open(io.BytesIO(raw)).verify()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="参考图无法读取，请更换图片") from exc
        raws.append(raw)
    qa = [_qa_image(r, i) for i, r in enumerate(raws)]
    strength = max(0.0, min(1.0, float(reference_strength)))
    params = {"prompt": prompt, "scene": _safe_name(scene, "studio"), "count": count,
              "strength": strength, "lock_product": lock_product,
              "negative_prompt": negative_prompt, "size": size, "sku": _safe_name(sku, "sku"),
              "seed_base": int(seed_base)}
    job = _new_job(request.app.state.settings, request.app.state.provider, raws[primary_index], params)
    return {"job_id": job["id"], "status": "generating", "count": count,
            "qa": qa, "primary_index": primary_index, "reference_count_used": 1}


@router.get("/api/demo/jobs")
def list_jobs(request: Request) -> dict:
    root = Path(request.app.state.settings.data_dir) / "demo"
    summaries = []
    paths = sorted(root.glob("*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
    for path in paths:
        try:
            job = _get_job(path.parent.name, request)
            with job["lock"]:
                summaries.append(_job_summary(job))
        except HTTPException:
            continue
    return {"jobs": sorted(summaries, key=lambda j: j["created_at"], reverse=True)}


@router.get("/api/demo/jobs/{job_id}")
def job_status(job_id: str, request: Request) -> dict:
    job = _get_job(job_id, request)
    with job["lock"]:
        return {**_job_summary(job), "images": [dict(img) if img else None for img in job["images"]], "params": dict(job["params"]),
                "can_retry": job["raw"] is not None,
                "reference_url": f"/api/demo/jobs/{job_id}/reference" if job["raw"] else None}


@router.get("/api/demo/jobs/{job_id}/reference")
def job_reference(job_id: str, request: Request):
    job = _get_job(job_id, request)
    if not job["raw"]:
        raise HTTPException(status_code=404, detail="旧任务未保存参考图")
    return Response(content=job["raw"], media_type=_detect_mime(job["raw"]))


@router.post("/api/demo/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    job = _get_job(job_id, request)
    with job["lock"]:
        if job["status"] in ACTIVE_STATES:
            job["cancel"].set()
            job["status"] = "canceling"
            _save_manifest(request.app.state.settings, job)
        return {"job_id": job_id, "status": job["status"]}


@router.post("/api/demo/jobs/{job_id}/retry")
def retry_job(request: Request, job_id: str, body: RetryBody) -> dict:
    job = _get_job(job_id, request)
    with job["lock"]:
        if job["status"] in ACTIVE_STATES:
            raise HTTPException(status_code=409, detail="请等待当前任务结束后重绘")
        if job["raw"] is None:
            raise HTTPException(status_code=409, detail="旧任务未保存参考图，请重新上传后生成")
        if getattr(request.app.state.provider, "name", "stub") != job["provider_name"]:
            raise HTTPException(status_code=409, detail="当前生图通道与历史任务不同，请恢复原配置后重试")
        indices = sorted(set(body.indices)) if body.indices is not None else [
            i for i, x in enumerate(job["images"]) if not x or x["status"] != "success"]
        if any(i < 0 or i >= len(job["images"]) for i in indices):
            raise HTTPException(status_code=400, detail="图片序号无效")
        if not indices:
            return {"job_id": job_id, "status": job["status"], "retried": 0}
        seeds = {}
        for i in indices:
            old = job["images"][i]
            if body.seed_mode == "same" and old and old.get("seed") is not None:
                seeds[i] = old["seed"]
            else:
                seeds[i] = job["next_seed"] % 2147483647
                job["next_seed"] += 1
            job["images"][i] = None
        job["provider"] = request.app.state.provider
        job["cancel"].clear()
        job["status"] = "generating"
        _save_manifest(request.app.state.settings, job)
        threading.Thread(target=_run_job, args=(request.app.state.settings, job, seeds), daemon=True).start()
        return {"job_id": job_id, "status": "generating", "retried": len(indices)}


@router.get("/api/demo/export")
def export(request: Request, session_id: str):
    job = _get_job(session_id, request)
    with job["lock"]:
        successful = [(i, img) for i, img in enumerate(job["images"])
                      if img and img["status"] == "success"]
        if not successful:
            raise HTTPException(status_code=409, detail="暂无成功图片可导出")
        _save_manifest(request.app.state.settings, job)
        out_dir = _job_dir(request.app.state.settings, job["id"])
        names = [_image_filename(job, i, img) for i, img in successful]
        names += ["manifest.json", "manifest.csv"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                path = out_dir / name
                if not path.is_file():
                    raise HTTPException(status_code=409, detail="图片文件缺失，请重试生成")
                zf.write(path, arcname=name)
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={job['id']}.zip"})
