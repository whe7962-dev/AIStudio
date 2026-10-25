"""P7 模型管理：model_manager（list / verify / activate / download）。

下载属设备主动拉取（不算上传），仍记审计；热切换排到 step 边界执行。
骨架阶段只实现注册表 list / 文件校验 / 激活占位；真实下载与量化热切换待硬化。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .registry import register, Tool

_TOOL = Tool(
    name="model_manager",
    description="模型注册表查询、哈希校验、激活（热切换排队到 step 边界）、设备主动下载。",
    json_schema={
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["list", "verify", "activate", "download"]},
            "model_id": {"type": "string"},
            "path": {"type": "string"},
            "sha256": {"type": "string"},
        },
        "required": ["op"],
    },
    permission="allow",
    destructive=False,
    network=False,
    layer="⑥",
)


def _find_model(ctx, model_id: str) -> dict | None:
    for group in ctx.config.get("model_registry", {}).values():
        for m in group:
            if m.get("id") == model_id:
                return m
    return None


def handler(params: dict, ctx, confirmed: bool) -> dict:
    op = params["op"]
    registry = ctx.config.get("model_registry", {})

    if op == "list":
        return {"models": registry}

    if op == "verify":
        path = Path(params["path"])
        if not path.exists():
            return {"model_id": params.get("model_id"), "ok": False, "reason": "文件缺失"}
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = params.get("sha256") or (_find_model(ctx, params.get("model_id", "")) or {}).get("sha256", "")
        return {"model_id": params.get("model_id"), "ok": bool(expected) and sha == expected,
                "sha256": sha, "expected": expected}

    if op == "activate":
        model_id = params["model_id"]
        if _find_model(ctx, model_id) is None:
            raise ValueError(f"未登记模型: {model_id}")
        ctx.cache["active_model"] = model_id
        return {"activated": model_id,
                "note": "热切换排到 step 边界执行；运行中任务完成后生效"}

    if op == "download":
        model = _find_model(ctx, params.get("model_id", ""))
        if model is None:
            raise ValueError(f"未登记模型: {params.get('model_id')}")
        # 骨架占位：真实下载由设备主动拉取 + 校验 + 登记；此处不实现网络下载
        return {"model_id": model["id"], "status": "stub",
                "note": "设备主动拉取（非上传）；骨架阶段未实现真实下载，待硬化"}

    raise ValueError(f"unknown op: {op}")


_TOOL.handler = handler
register(_TOOL)
