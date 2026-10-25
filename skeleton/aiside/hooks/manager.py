"""Hook 管理器（对应 s04）：工具执行前后扩展点 + 网络出口审计。

- PreToolUse 可返回阻断原因（block_reason），阻断后该工具不执行。
- PostToolUse 观察结果，异常不影响主循环。
- 网络出口审计：任何带 network 的工具执行，记录域名、字节数、时间、触发来源。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from ..core.audit import AuditLog

logger = logging.getLogger("aiside.hooks")


@dataclass
class HookContext:
    tool_name: str
    params: dict[str, Any]
    result: Any = None
    network: bool = False
    network_domain: str | None = None
    bytes_sent: int = 0


PreHook = Callable[[HookContext], str | None]
PostHook = Callable[[HookContext], None]


class HookManager:
    def __init__(self, audit: AuditLog):
        self._pre: list[PreHook] = []
        self._post: list[PostHook] = []
        self._stop: list[Callable[[], None]] = []
        self.audit = audit
        # 内置网络出口审计
        self.register_pre(self._audit_network_pre)
        self.register_post(self._audit_network_post)

    def register_pre(self, hook: PreHook) -> None:
        self._pre.append(hook)

    def register_post(self, hook: PostHook) -> None:
        self._post.append(hook)

    def trigger_pre(self, ctx: HookContext) -> str | None:
        for hook in self._pre:
            try:
                reason = hook(ctx)
                if reason:
                    logger.warning("PreToolUse blocked tool=%s reason=%s", ctx.tool_name, reason)
                    return reason
            except Exception as exc:  # noqa: BLE001 - hook 异常不影响主循环
                logger.exception("PreToolUse hook error: %s", exc)
        return None

    def trigger_post(self, ctx: HookContext) -> None:
        for hook in self._post:
            try:
                hook(ctx)
            except Exception as exc:  # noqa: BLE001
                logger.exception("PostToolUse hook error: %s", exc)

    # ---- 内置钩子 ----
    def _audit_network_pre(self, ctx: HookContext) -> str | None:
        if ctx.network:
            if not ctx.network_domain:
                return "network tool without domain"
        return None

    def _audit_network_post(self, ctx: HookContext) -> None:
        if ctx.network:
            self.audit.record(
                "network_egress",
                tool=ctx.tool_name,
                domain=ctx.network_domain,
                bytes_sent=ctx.bytes_sent,
            )
