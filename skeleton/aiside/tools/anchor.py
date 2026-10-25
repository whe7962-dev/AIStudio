"""P2 一致性锚点：build_consistency_anchor。

骨架阶段：以质检通过的实拍图 + 商品理解为输入，产出锚点包（JSON）+ 保真度基准。
真实实现替换为 reference pack + LoRA/IP-Adapter/ControlNet 选择，接口不变。
"""

from __future__ import annotations

import json
import time

from .registry import register, Tool

_TOOL = Tool(
    name="build_consistency_anchor",
    description="由质检通过的实拍图生成一致性锚点（reference pack + 保真度基准）。",
    json_schema={
        "type": "object",
        "properties": {
            "photo_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "template_id": {"type": "string"},
            "product_understanding": {"type": "string"},
            "node_id": {"type": "string"},
        },
        "required": ["photo_ids"],
    },
    permission="allow",
    network=False,
    layer="④",
)


def handler(params: dict, ctx, confirmed: bool) -> dict:
    photo_ids = params["photo_ids"]
    for pid in photo_ids:
        if not ctx.assets.exists(pid):
            raise ValueError(f"asset not found: {pid}")

    doc = {
        "kind": "anchor",
        "photo_ids": photo_ids,
        "template_id": params.get("template_id", ""),
        "product_understanding": params.get("product_understanding", ""),
        "created_at": time.time(),
    }
    anchor_id = ctx.assets.put(
        json.dumps(doc, ensure_ascii=False).encode("utf-8"), {"kind": "anchor"})
    # 骨架占位保真度：真实实现为与参考图的相似度评分
    fidelity = 1.0

    affected: list[str] = []
    node_id = params.get("node_id")
    if node_id:
        node = ctx.project.get(node_id)
        outputs = {"anchor_asset_id": anchor_id, "fidelity": fidelity}
        ctx.project.set_status(node_id, "done", outputs)
        # 锚点变更触发全项目重算提示：下游标 dirty，自身保持 done
        affected = sorted(ctx.project.invalidate_downstream(node_id))

    return {"anchor_asset_id": anchor_id, "fidelity": fidelity,
            "downstream_dirty": affected}


_TOOL.handler = handler
register(_TOOL)
