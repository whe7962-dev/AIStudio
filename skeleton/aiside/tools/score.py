"""E3 一致性评分与批次 QA：score_fidelity_and_batch_qa。

骨架阶段用轻量像素相似度（32x32 灰度 L2）模拟 DINO 相似度；真实 DINO 接入后替换
_similarity，接口不变。只读，不改动图像与项目图。
"""

from __future__ import annotations

import io
import json

from PIL import Image

from .registry import register, Tool

_TOOL = Tool(
    name="score_fidelity_and_batch_qa",
    description="单图保真度分 + 批次一致性分 + 渠道规格符合性检查（只读）。",
    json_schema={
        "type": "object",
        "properties": {
            "asset_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "baseline_asset_id": {"type": "string"},
            "anchor_id": {"type": "string"},
            "channel": {"type": "string"},
            "node_id": {"type": "string"},
        },
        "required": ["asset_ids"],
    },
    permission="allow",
    network=False,
    layer="⑦",
)


def _image(asset_store, cid: str) -> Image.Image:
    data = asset_store.get(cid)
    img = Image.open(io.BytesIO(data)).convert("L").resize((32, 32))
    return img


def _similarity(a: Image.Image, b: Image.Image) -> float:
    pa = list(a.getdata())
    pb = list(b.getdata())
    diff = sum(abs(x - y) for x, y in zip(pa, pb)) / (len(pa) * 255)
    return round(max(0.0, 1.0 - diff), 4)


def _baseline_id(ctx, params: dict) -> str:
    if params.get("baseline_asset_id"):
        return params["baseline_asset_id"]
    if params.get("anchor_id"):
        doc = json.loads(ctx.assets.get(params["anchor_id"]).decode("utf-8"))
        return doc["photo_ids"][0]
    return params["asset_ids"][0]


def handler(params: dict, ctx, confirmed: bool) -> dict:
    asset_ids = params["asset_ids"]
    baseline_id = _baseline_id(ctx, params)
    baseline_img = _image(ctx.assets, baseline_id)

    fidelity = []
    for cid in asset_ids:
        fidelity.append({"asset_id": cid, "score": _similarity(baseline_img, _image(ctx.assets, cid))})

    # 批次一致性：两两相似度均值
    sims = []
    for i in range(len(asset_ids)):
        for j in range(i + 1, len(asset_ids)):
            sims.append(_similarity(_image(ctx.assets, asset_ids[i]),
                                    _image(ctx.assets, asset_ids[j])))
    batch_consistency = round(sum(sims) / len(sims), 4) if sims else 1.0

    # 规格符合性（渠道尺寸）
    spec_check = {"passed": True, "reasons": []}
    channel_id = params.get("channel")
    if channel_id:
        for ch in ctx.channels:
            if ch.get("id") == channel_id:
                spec = ch["specs"][0]
                for cid in asset_ids:
                    img = Image.open(io.BytesIO(ctx.assets.get(cid)))
                    if (img.width, img.height) != (spec["width"], spec["height"]):
                        spec_check["passed"] = False
                        spec_check["reasons"].append(
                            f"{cid}: {img.width}x{img.height} != {spec['width']}x{spec['height']}")
                break

    node_id = params.get("node_id")
    if node_id:
        ctx.project.set_status(node_id, "done", {
            "fidelity": fidelity, "batch_consistency": batch_consistency,
            "spec_check": spec_check,
        })

    return {"fidelity": fidelity, "batch_consistency": batch_consistency,
            "spec_check": spec_check,
            "suggest_repaint": [f["asset_id"] for f in fidelity
                                if f["score"] < ctx.config.get("fidelity", {}).get("single_fidelity_min", 0.0)]}


_TOOL.handler = handler
register(_TOOL)
