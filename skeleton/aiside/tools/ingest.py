"""E1 商品理解与抠图：ingest_and_qa_photos。

骨架阶段：读取实拍图 → 内容寻址入库（原始不修改）→ 生成占位抠图蒙版 → 质检门禁。
真实抠图/质检模型接入后替换 _build_mask 与 _qa 内部实现，接口不变。
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from .registry import register, Tool

_TOOL = Tool(
    name="ingest_and_qa_photos",
    description="上传 3-5 张实拍图，自动抠图（蒙版）+ 质检门禁；不修改原始文件，不联网。",
    json_schema={
        "type": "object",
        "properties": {
            "sku_id": {"type": "string"},
            "image_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["image_paths"],
    },
    permission="allow",
    network=False,
    layer="④",
)


def _qa(img: Image.Image, thresholds: dict) -> dict:
    w, h = img.size
    reasons = []
    if w < thresholds.get("min_width", 512) or h < thresholds.get("min_height", 512):
        reasons.append("分辨率过低")
    ratio = max(w, h) / max(1, min(w, h))
    if ratio > thresholds.get("max_aspect_ratio", 2.0):
        reasons.append("宽高比异常")
    return {"ok": not reasons, "reasons": reasons, "width": w, "height": h}


def _build_mask(img: Image.Image) -> bytes:
    # 占位蒙版：全白 alpha（真实抠图模型接入后替换）
    mask = Image.new("L", img.size, 255)
    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


def handler(params: dict, ctx, confirmed: bool) -> dict:
    thresholds = ctx.config.get("qa", {})
    results = []
    for path in params["image_paths"]:
        p = Path(path)
        if not p.exists():
            results.append({"path": str(p), "qa": {"ok": False, "reasons": ["文件不存在"]}})
            continue
        data = p.read_bytes()
        img = Image.open(io.BytesIO(data))
        img.load()
        source_id = ctx.assets.put(data, {"kind": "source", "sku_id": params.get("sku_id"),
                                          "filename": p.name})
        mask_id = ctx.assets.put(_build_mask(img), {"kind": "mask", "source": source_id})
        qa = _qa(img, thresholds)
        results.append({"path": str(p), "source_asset_id": source_id,
                        "mask_asset_id": mask_id, "qa": qa})
    return {"items": results, "passed": [r for r in results if r.get("qa", {}).get("ok")]}


_TOOL.handler = handler
register(_TOOL)
