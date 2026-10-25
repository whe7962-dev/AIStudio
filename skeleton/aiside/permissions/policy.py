"""权限策略（对应 s03）。

红线落地：
- 网络出口默认拒绝；仅放行白名单域名（demo 生图 API 域名，用户提供 key 即显式勾选）。
- 导出打包、删除节点/改上游等破坏性操作需要用户确认（ask）。
- 每次决策写审计日志，禁止静默。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.audit import AuditLog

ALLOW = "allow"
ASK = "ask"
DENY = "deny"


@dataclass
class Decision:
    action: str
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW


@dataclass
class ActionContext:
    tool_name: str
    params: dict[str, Any]
    confirmed: bool = False
    permission: str = ALLOW          # allow | ask
    destructive: bool = False
    network: bool = False
    network_domain: str | None = None


class PermissionPolicy:
    def __init__(self, settings, audit: AuditLog):
        self.settings = settings
        self.audit = audit

    def evaluate(self, ctx: ActionContext) -> Decision:
        # 1) 网络红线：默认拒绝上传
        if ctx.network:
            domain = (ctx.network_domain or "").lower()
            if not domain or not self.settings.allowed_network_domain(
                    f"https://{domain}"):
                self._audit(DENY, ctx, "network egress not in allowlist")
                return Decision(DENY, "网络出口默认拒绝：域名不在白名单（默认不出网红线）")

        # 2) 破坏性 / 需确认操作
        if (ctx.permission == ASK or ctx.destructive) and not ctx.confirmed:
            self._audit(ASK, ctx, "requires user confirmation")
            return Decision(ASK, "该操作需要用户确认")

        self._audit(ALLOW, ctx, "policy allow")
        return Decision(ALLOW)

    def _audit(self, action: str, ctx: ActionContext, reason: str) -> None:
        self.audit.record(
            "permission",
            action=action,
            tool=ctx.tool_name,
            confirmed=ctx.confirmed,
            destructive=ctx.destructive,
            network=ctx.network,
            network_domain=ctx.network_domain,
            reason=reason,
        )
