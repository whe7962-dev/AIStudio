import json

from aiside.loop import AgentLoop, ModelResponse, OpenAICompatClient, ToolCall
from aiside.tools.registry import openai_tool_schemas


def test_openai_tool_schemas():
    schemas = openai_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "generate_image" in names
    assert "postprocess_and_package" in names
    assert len(schemas) == 8


def test_openai_client_parse():
    data = {
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "asset_store", "arguments": '{"op": "list"}'},
                }],
            },
        }],
    }
    resp = OpenAICompatClient._parse(data)
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].name == "asset_store"
    assert resp.tool_calls[0].arguments == {"op": "list"}


class _ScriptedClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, messages, tools):
        return self.responses.pop(0)


def test_agent_loop_dispatches_tool(workspace):
    ctx = workspace.create_project()
    client = _ScriptedClient([
        ModelResponse(finish_reason="tool_calls",
                      tool_calls=[ToolCall(id="c1", name="asset_store",
                                           arguments={"op": "list"})]),
        ModelResponse(finish_reason="stop", content="done"),
    ])
    loop = AgentLoop(workspace, ctx.project.project_id, client)
    result = loop.run("列出资产")
    assert result["stop_reason"] == "stop"
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 1
    assert json.loads(tool_msgs[0]["content"])["status"] == "ok"


def test_agent_loop_surfaces_ask(workspace, tmp_path):
    ctx = workspace.create_project()
    # 让模型直接调用导出工具但不确认 → 应回传 ask，而不是执行
    client = _ScriptedClient([
        ModelResponse(finish_reason="tool_calls",
                      tool_calls=[ToolCall(
                          id="c1", name="postprocess_and_package",
                          arguments={"asset_id": "x", "channels": ["douyin"],
                                     "output_dir": str(tmp_path / "out")})]),
        ModelResponse(finish_reason="stop", content="waiting"),
    ])
    loop = AgentLoop(workspace, ctx.project.project_id, client)
    result = loop.run("导出素材")
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert tool_msgs[0]["content"].count("ask") == 1
