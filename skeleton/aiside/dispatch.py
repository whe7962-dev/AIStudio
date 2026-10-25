"""工具分发器：loop + 工具分派 + hooks + 权限 + 重试 + 观测。

对应 s01/s02/s03/s04/s05/s15 集成的最小可运行骨架：
模型循环用确定性分派承载（真实 LLM 循环接入后不变本层接口）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from .core.context import RuntimeContext
from .errors import ConfirmationRequired, PermissionDenied, ToolExecutionError
from .hooks.manager import HookContext, HookManager
from .observability.metrics import Metrics
from .permissions.policy import ActionContext, ASK, DENY, PermissionPolicy
from .tools.registry import get_tool

logger = logging.getLogger("aiside.dispatch")

_DESTRUCTIVE_GRAPH_OPS = {"remove_node", "update_params", "connect"}


class Dispatcher:
    def __init__(self, settings, policy: PermissionPolicy, hooks: HookManager,
                 metrics: Metrics):
        self.settings = settings
        self.policy = policy
        self.hooks = hooks
        self.metrics = metrics

    def evaluate(self, tool_name: str, params: dict, ctx: RuntimeContext,
                 confirmed: bool = False):
        """只做权限评估（不执行），供 API 先判断 allow / ask / deny。"""
        tool = get_tool(tool_name)  # 未注册工具 → 拒绝执行
        network = tool.network
        network_domain = None
        if tool_name == "generate_image" and getattr(ctx.provider, "name", "") == "seedream":
            network = True
            network_domain = getattr(ctx.provider, "network_domain", "")
        destructive = tool.destructive
        permission = tool.permission
        if tool_name == "project_graph_edit" and params.get("op") in _DESTRUCTIVE_GRAPH_OPS:
            destructive = True
            permission = ASK
        action = ActionContext(
            tool_name=tool_name, params=params, confirmed=confirmed,
            permission=permission, destructive=destructive,
            network=network, network_domain=network_domain,
        )
        return self.policy.evaluate(action)

    def dispatch(self, tool_name: str, params: dict, ctx: RuntimeContext,
                 confirmed: bool = False) -> dict:
        tool = get_tool(tool_name)  # 未注册工具 → 拒绝执行
        decision = self.evaluate(tool_name, params, ctx, confirmed)
        if decision.action == DENY:
            raise PermissionDenied(decision.reason)
        if decision.action == ASK:
            raise ConfirmationRequired(tool_name, decision.reason)

        network = tool.network
        network_domain = None
        if tool_name == "generate_image" and getattr(ctx.provider, "name", "") == "seedream":
            network = True
            network_domain = getattr(ctx.provider, "network_domain", "")

        hook_ctx = HookContext(tool_name=tool_name, params=params,
                               network=network, network_domain=network_domain)
        block_reason = self.hooks.trigger_pre(hook_ctx)
        if block_reason:
            raise PermissionDenied(f"PreToolUse 阻断: {block_reason}")

        start = time.monotonic()
        try:
            result = self._execute_with_retry(tool_name, params, ctx, confirmed)
        except Exception as exc:  # noqa: BLE001 - 转统一错误并保留原因
            self.metrics.inc(f"tool.{tool_name}.errors")
            raise ToolExecutionError(f"{tool_name} 执行失败: {exc}") from exc
        finally:
            self.metrics.observe(f"tool.{tool_name}.latency", time.monotonic() - start)

        self.metrics.inc(f"tool.{tool_name}.calls")
        hook_ctx.result = result
        self.hooks.trigger_post(hook_ctx)
        logger.info("tool executed tool=%s", tool_name)
        return result

    def _execute_with_retry(self, tool_name: str, params: dict, ctx: RuntimeContext,
                            confirmed: bool) -> Any:
        tool = get_tool(tool_name)
        last_exc: Exception | None = None
        for attempt in range(2):  # 失败自动重试 1 次
            try:
                return tool.handler(params, ctx, confirmed)
            except (PermissionError, ConfirmationRequired, PermissionDenied):
                raise
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("tool retry tool=%s attempt=%s err=%s", tool_name, attempt, exc)
        raise last_exc  # type: ignore[misc]
