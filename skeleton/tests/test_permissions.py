from aiside.core.audit import AuditLog
from aiside.permissions.policy import ActionContext, ASK, DENY, ALLOW, PermissionPolicy
from aiside.settings import Settings


def test_network_default_deny(tmp_path):
    settings = Settings(provider="stub", network_allowlist=["api.example.com"])
    policy = PermissionPolicy(settings, AuditLog(tmp_path / "audit.jsonl"))
    ctx = ActionContext(tool_name="upload", params={}, network=True, network_domain="evil.com")
    decision = policy.evaluate(ctx)
    assert decision.action == DENY


def test_network_allowlist(tmp_path):
    settings = Settings(provider="stub", network_allowlist=["api.example.com"])
    policy = PermissionPolicy(settings, AuditLog(tmp_path / "audit.jsonl"))
    ctx = ActionContext(tool_name="generate_image", params={}, network=True,
                        network_domain="api.example.com")
    assert policy.evaluate(ctx).action == ALLOW


def test_export_requires_confirmation(tmp_path):
    settings = Settings(provider="stub")
    policy = PermissionPolicy(settings, AuditLog(tmp_path / "audit.jsonl"))
    ctx = ActionContext(tool_name="postprocess_and_package", params={}, permission=ASK)
    assert policy.evaluate(ctx).action == ASK
    ctx.confirmed = True
    assert policy.evaluate(ctx).action == ALLOW


def test_destructive_requires_confirmation(tmp_path):
    settings = Settings(provider="stub")
    policy = PermissionPolicy(settings, AuditLog(tmp_path / "audit.jsonl"))
    ctx = ActionContext(tool_name="project_graph_edit", params={"op": "remove_node"},
                        destructive=True)
    assert policy.evaluate(ctx).action == ASK


def test_audit_records_decision(tmp_path):
    settings = Settings(provider="stub")
    audit = AuditLog(tmp_path / "audit.jsonl")
    policy = PermissionPolicy(settings, audit)
    policy.evaluate(ActionContext(tool_name="upload", params={}, network=True,
                                  network_domain="evil.com"))
    assert any(e["event"] == "permission" and e["action"] == DENY for e in audit.events)
