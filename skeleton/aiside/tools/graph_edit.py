"""P1 项目图编辑：project_graph_edit（新增 / 改参数 / 删除 / 重连）。

删除节点与改动上游属破坏性操作（丢弃下游中间结果），需用户确认，确认后仍可撤销。
"""

from __future__ import annotations

from .registry import register, Tool

_TOOL = Tool(
    name="project_graph_edit",
    description="编辑项目图（DAG）：新增节点 / 改参数 / 删除节点 / 重连上游；破坏性操作需确认。",
    json_schema={
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["add_node", "update_params", "remove_node", "connect"]},
            "node_id": {"type": "string"},
            "node_type": {"type": "string"},
            "params": {"type": "object"},
            "upstream": {"type": "array", "items": {"type": "string"}},
            "downstream": {"type": "string"},
        },
        "required": ["op"],
    },
    permission="allow",  # 破坏性 op 在 handler 内按 destructive 二次确认（dispatcher 会传 confirmed）
    destructive=False,
    network=False,
    layer="③",
)

_DESTRUCTIVE_OPS = {"remove_node", "update_params", "connect"}


def handler(params: dict, ctx, confirmed: bool) -> dict:
    op = params["op"]
    if op in _DESTRUCTIVE_OPS and not confirmed:
        raise PermissionError(f"操作 {op} 属破坏性操作，需用户确认（可由撤销栈回滚）")

    graph = ctx.project
    if op == "add_node":
        node = graph.add_node(params.get("node_type", "generic"), params.get("params") or {},
                              upstream=params.get("upstream") or [])
        return {"node_id": node.id, "affected": [node.id]}

    if op == "update_params":
        affected = graph.update_params(params["node_id"], params.get("params") or {})
        return {"node_id": params["node_id"], "affected": sorted(affected)}

    if op == "remove_node":
        affected = graph.remove_node(params["node_id"])
        return {"node_id": params["node_id"], "affected": sorted(affected)}

    if op == "connect":
        graph.connect(params["upstream"], params["downstream"])
        return {"upstream": params["upstream"], "downstream": params["downstream"],
                "affected": sorted(graph.downstream(params["downstream"]))}

    raise ValueError(f"unknown op: {op}")


_TOOL.handler = handler
register(_TOOL)
