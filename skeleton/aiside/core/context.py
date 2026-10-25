"""工具运行上下文：把项目图、资产库、journal、provider、配置聚合给工具处理器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .asset_store import AssetStore
from .job_journal import JobJournal
from .project_graph import ProjectGraph


@dataclass
class RuntimeContext:
    project: ProjectGraph
    assets: AssetStore
    journal: JobJournal
    provider: Any  # ImageProvider
    settings: Any  # Settings
    workspace: Path = field(default_factory=Path)
    config: dict[str, Any] = field(default_factory=dict)
    cache: dict[str, Any] = field(default_factory=dict)
    # 由调度器在 job 执行时注入：step 边界 checkpoint / 取消检查
    checkpoint: Callable[[dict], None] | None = None
    is_cancelled: Callable[[], bool] | None = None

    @property
    def channels(self) -> list[dict]:
        return self.config.get("channels", [])
