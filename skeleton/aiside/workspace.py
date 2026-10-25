"""工作区：聚合配置、项目、调度、权限、观测，供 API / CLI 使用。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from .core.asset_store import AssetStore
from .core.audit import AuditLog
from .core.context import RuntimeContext
from .core.ids import new_id
from .core.job_journal import AWAITING_CONFIRMATION, JobJournal
from .core.project_graph import ProjectGraph
from .core.scheduler import Scheduler
from .dispatch import Dispatcher
from .errors import ConfirmationRequired, PermissionDenied
from .hooks.manager import HookManager
from .observability.metrics import Metrics
from .permissions.policy import Decision, PermissionPolicy
from .providers import get_provider

logger = logging.getLogger("aiside.workspace")


class Workspace:
    def __init__(self, settings):
        self.settings = settings
        self.data_dir = Path(settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.audit = AuditLog(self.data_dir / "audit.jsonl")
        self.metrics = Metrics()
        self.hooks = HookManager(self.audit)
        self.policy = PermissionPolicy(settings, self.audit)
        self.dispatcher = Dispatcher(settings, self.policy, self.hooks, self.metrics)
        self.scheduler = Scheduler()
        self.provider = get_provider(settings)
        self.config = self._load_config()
        self._projects: dict[str, RuntimeContext] = {}
        self._results: dict[str, dict] = {}
        self._confirmations: dict[str, dict] = {}
        self.scheduler.start()

    # ---- 配置 ----
    def _load_config(self) -> dict:
        """读取 config/*.yaml，展平为一致的一层结构。"""
        cfg: dict[str, Any] = {}
        files = {
            "channels.yaml": ("channels", "channels"),
            "qa_thresholds.yaml": None,   # 含 qa / fidelity 两个子键
            "naming_rules.yaml": ("naming", "naming"),
            "model_registry.yaml": ("model_registry", "models"),
            "scheduling.yaml": None,       # 含 scheduling / degradation 两个子键
        }
        for filename, pair in files.items():
            path = self.settings.config_dir / filename
            if not path.exists():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if pair is None:
                for k, v in data.items():
                    cfg[k] = v or {}
            else:
                key, subkey = pair
                cfg[key] = data.get(subkey, {})
        return cfg

    # ---- 项目 ----
    def create_project(self, project_id: str | None = None) -> RuntimeContext:
        pid = project_id or new_id("proj")
        project_dir = self.data_dir / "projects" / pid
        graph = ProjectGraph(pid)
        assets = AssetStore(project_dir / "assets")
        journal = JobJournal(project_dir / "journal.sqlite3")
        ctx = RuntimeContext(
            project=graph, assets=assets, journal=journal,
            provider=self.provider, settings=self.settings,
            workspace=project_dir, config=self.config,
        )
        graph.save(project_dir / "project.json")
        self._projects[pid] = ctx
        return ctx

    def get_project(self, project_id: str) -> RuntimeContext:
        if project_id not in self._projects:
            project_dir = self.data_dir / "projects" / project_id
            graph = ProjectGraph.load(project_dir / "project.json")
            ctx = RuntimeContext(
                project=graph,
                assets=AssetStore(project_dir / "assets"),
                journal=JobJournal(project_dir / "journal.sqlite3"),
                provider=self.provider, settings=self.settings,
                workspace=project_dir, config=self.config,
            )
            self._projects[project_id] = ctx
        return self._projects[project_id]

    # ---- 任务提交 ----
    def check_permission(self, project_id: str, tool_name: str, params: dict) -> Decision:
        ctx = self.get_project(project_id)
        return self.dispatcher.evaluate(tool_name, params, ctx, confirmed=False)

    def submit(self, project_id: str, tool_name: str, params: dict,
               priority: str = "batch", confirmed: bool = False) -> dict:
        ctx = self.get_project(project_id)
        decision = self.dispatcher.evaluate(tool_name, params, ctx, confirmed)
        job_id = new_id("job")

        if decision.action == "ask":
            self._confirmations[job_id] = {
                "project_id": project_id, "tool_name": tool_name, "params": params,
                "priority": priority,
            }
            ctx.journal.record(job_id, tool_name, params, status=AWAITING_CONFIRMATION,
                               project_id=project_id)
            return {"job_id": job_id, "status": "awaiting_confirmation",
                    "reason": decision.reason}

        ctx.journal.record(job_id, tool_name, params, project_id=project_id, status="queued")
        self.scheduler.submit(
            job_id,
            lambda jid, jctx: self._run_job(jid, ctx, tool_name, params, confirmed, jctx),
            priority=priority,
        )
        return {"job_id": job_id, "status": "queued"}

    def confirm(self, job_id: str) -> dict:
        pending = self._confirmations.pop(job_id, None)
        if pending is None:
            raise PermissionDenied(f"job 不在等待确认状态: {job_id}")
        return self.submit(pending["project_id"], pending["tool_name"],
                           pending["params"], priority=pending["priority"], confirmed=True)

    def _run_job(self, job_id: str, ctx: RuntimeContext, tool_name: str,
                 params: dict, confirmed: bool, jctx=None) -> None:
        # 注入 step 边界能力：工具可写 checkpoint、可检查取消
        ctx.checkpoint = lambda data: ctx.journal.checkpoint(job_id, data)
        ctx.is_cancelled = (jctx.is_cancelled if jctx is not None else (lambda: False))
        ctx.journal.update(job_id, "running")
        try:
            result = self.dispatcher.dispatch(tool_name, params, ctx, confirmed)
            self._results[job_id] = result
            degraded = isinstance(result, dict) and bool(result.get("degraded"))
            ctx.journal.update(job_id, "degraded" if degraded else "completed")
        except ConfirmationRequired as exc:
            # 异步执行中不应再出现 ask（提交前已评估）；防御性留痕
            ctx.journal.update(job_id, AWAITING_CONFIRMATION, error=exc.reason)
            raise
        except Exception as exc:  # noqa: BLE001 - scheduler 会标记 failed
            ctx.journal.update(job_id, "failed", error=str(exc))
            raise

    # ---- 恢复（S2-2） ----
    def recover_incomplete(self, project_id: str) -> list[dict]:
        """扫描单个项目未完成任务，供续跑。"""
        ctx = self.get_project(project_id)
        return [ctx.journal.get(jid) for jid in ctx.journal.recover_incomplete()
                if ctx.journal.get(jid) is not None]

    def resume_job(self, project_id: str, job_id: str) -> dict:
        """从 checkpoint 续跑一个未完成任务（新起 job，携带 resume 参数）。"""
        ctx = self.get_project(project_id)
        record = ctx.journal.get(job_id)
        if record is None:
            raise PermissionDenied(f"job 不存在: {job_id}")
        params = dict(record.get("params_json") or {})
        checkpoint = record.get("checkpoint_json") or {}
        if checkpoint.get("done"):
            params["resume"] = {"done": checkpoint["done"],
                                 "asset_ids": checkpoint.get("asset_ids", [])}
        return self.submit(project_id, record["tool"], params,
                           priority="batch", confirmed=True)

    def scan_incomplete_jobs(self) -> list[dict]:
        """启动时扫描所有项目 journal，列出未完成任务（恢复率观测点）。"""
        result = []
        projects_root = self.data_dir / "projects"
        if not projects_root.is_dir():
            return result
        for project_dir in projects_root.iterdir():
            journal_path = project_dir / "journal.sqlite3"
            if not journal_path.exists():
                continue
            journal = JobJournal(journal_path)
            for jid in journal.recover_incomplete():
                rec = journal.get(jid)
                if rec:
                    result.append({"project_id": project_dir.name, "job_id": jid,
                                   "tool": rec.get("tool"), "status": rec.get("status")})
            journal.close()
        return result

    # ---- 查询 ----
    def job_result(self, job_id: str) -> dict | None:
        return self._results.get(job_id)

    def job_status(self, project_id: str, job_id: str) -> dict:
        ctx = self.get_project(project_id)
        record = ctx.journal.get(job_id)
        if record is None:
            return {"job_id": job_id, "status": "unknown"}
        return {"job_id": job_id, "status": record["status"],
                "result": self._results.get(job_id), "error": record.get("error")}

    def close(self) -> None:
        self.scheduler.stop()
