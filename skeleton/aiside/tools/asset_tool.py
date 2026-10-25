"""P1 内容寻址资产库工具：asset_store（put / get / list / archive）。

不删除原始上传素材；archive 仅标记，purge 不暴露给模型。
"""

from __future__ import annotations

from pathlib import Path

from .registry import register, Tool

_TOOL = Tool(
    name="asset_store",
    description="内容寻址存取生成物与素材（put / get / list / archive）。",
    json_schema={
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["put", "get", "list", "archive"]},
            "path": {"type": "string"},
            "cid": {"type": "string"},
            "kind": {"type": "string"},
        },
        "required": ["op"],
    },
    permission="allow",
    destructive=False,
    network=False,
    layer="③",
)


def handler(params: dict, ctx, confirmed: bool) -> dict:
    op = params["op"]
    if op == "put":
        p = Path(params["path"])
        cid = ctx.assets.put(p.read_bytes(), {"kind": params.get("kind", "generic"),
                                              "source_path": str(p)})
        return {"cid": cid}
    if op == "get":
        return {"cid": params["cid"], "meta": ctx.assets.meta(params["cid"])}
    if op == "list":
        return {"items": ctx.assets.list()}
    if op == "archive":
        ctx.assets.archive(params["cid"])
        return {"cid": params["cid"], "archived": True}
    raise ValueError(f"unknown op: {op}")


_TOOL.handler = handler
register(_TOOL)
