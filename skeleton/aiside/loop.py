"""s01 Agent Loop：messages → model → tool_use → result → 循环。

- ModelClient 抽象：OpenAI 兼容；正式版指向本地 Qwen3（Ollama / LM Studio / MLX server）。
- 生产要点：stop_reason 完整处理、超时、429/5xx 重试、最大轮数。
- 权限 ask/deny 通过工具结果回传，不静默；导出/破坏性操作未确认时返回 ask。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import httpx

from .errors import ConfirmationRequired, PermissionDenied, ToolExecutionError
from .prompt import SYSTEM_PROMPT
from .tools.registry import openai_tool_schemas

logger = logging.getLogger("aiside.loop")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    finish_reason: str
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        ...


class OpenAICompatClient:
    """OpenAI 兼容 chat/completions 客户端（可指向本地 Qwen3 server）。"""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {"model": self.model, "messages": messages, "tools": tools}

        last_exc: Exception | None = None
        for attempt in range(2):  # 429/5xx 重试 1 次
            try:
                resp = httpx.post(f"{self.base_url}/chat/completions", headers=headers,
                                  json=body, timeout=self.timeout)
            except httpx.HTTPError as exc:
                last_exc = exc
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_exc = RuntimeError(f"LLM {resp.status_code}: {resp.text[:120]}")
                time.sleep(1.0 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"LLM {resp.status_code}: {resp.text[:200]}")
            return self._parse(resp.json())
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse(data: dict) -> ModelResponse:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish = choice.get("finish_reason") or "stop"
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id") or "", name=fn.get("name") or "",
                                       arguments=args))
        return ModelResponse(finish_reason=finish, content=msg.get("content") or "",
                             tool_calls=tool_calls)


class AgentLoop:
    def __init__(self, workspace, project_id: str, client: ModelClient,
                 max_iters: int = 20, system_prompt: str = SYSTEM_PROMPT):
        self.workspace = workspace
        self.project_id = project_id
        self.client = client
        self.max_iters = max_iters
        self.system_prompt = system_prompt

    def run(self, goal: str) -> dict:
        ctx = self.workspace.get_project(self.project_id)
        tools = openai_tool_schemas()
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": goal},
        ]

        for _ in range(self.max_iters):
            resp = self.client.complete(messages, tools)
            if resp.tool_calls:
                messages.append(self._assistant_message(resp))
                for tc in resp.tool_calls:
                    messages.append(self._tool_result(tc, ctx))
                continue
            return {"stop_reason": resp.finish_reason, "content": resp.content,
                    "messages": messages}

        return {"stop_reason": "max_iters", "content": "", "messages": messages}

    @staticmethod
    def _assistant_message(resp: ModelResponse) -> dict:
        return {
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments, ensure_ascii=False)}}
                for tc in resp.tool_calls
            ],
        }

    def _tool_result(self, tc: ToolCall, ctx) -> dict:
        try:
            result = self.workspace.dispatcher.dispatch(tc.name, tc.arguments, ctx, confirmed=False)
            payload = {"status": "ok", "result": result}
        except ConfirmationRequired as exc:
            payload = {"status": "ask", "tool": tc.name, "reason": exc.reason}
        except PermissionDenied as exc:
            payload = {"status": "deny", "tool": tc.name, "reason": str(exc)}
        except ToolExecutionError as exc:
            payload = {"status": "error", "tool": tc.name, "reason": str(exc)}
        return {"role": "tool", "tool_call_id": tc.id,
                "content": json.dumps(payload, ensure_ascii=False, default=str)}


def build_llm_client(settings):
    if not settings.llm_enabled:
        return None
    return OpenAICompatClient(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
