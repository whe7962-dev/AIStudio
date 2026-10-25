"""工具注册表（对应 s02）：JSON schema 严格、参数校验、错误回传格式统一。

工具处理器签名：handler(params: dict, ctx: RuntimeContext, confirmed: bool) -> dict
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.context import RuntimeContext

Handler = Callable[[dict, RuntimeContext, bool], dict]


@dataclass
class Tool:
    name: str
    description: str
    json_schema: dict
    handler: Handler = None  # 由各工具模块在定义 handler 后回填
    permission: str = "allow"       # allow | ask
    destructive: bool = False
    network: bool = False
    # 归属层（对齐方案工具清单的 7 层标注）
    layer: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "json_schema": self.json_schema,
            "permission": self.permission,
            "destructive": self.destructive,
            "network": self.network,
            "layer": self.layer,
        }


TOOLS: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    TOOLS[tool.name] = tool
    return tool


def get_tool(name: str) -> Tool:
    try:
        return TOOLS[name]
    except KeyError:
        raise KeyError(f"未注册工具: {name}（拒绝执行越权路径）")


def list_tools() -> list[Tool]:
    return list(TOOLS.values())


def openai_tool_schemas() -> list[dict]:
    """把注册表转成 OpenAI 兼容的 tools 列表（供 Agent Loop 使用）。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.json_schema,
            },
        }
        for t in TOOLS.values()
    ]
