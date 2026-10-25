"""审计日志：权限决策、网络出口、导出确认等安全事件留痕（JSONL + 内存）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def record(self, event: str, **fields: Any) -> None:
        entry = {"ts": time.time(), "event": event, **fields}
        self.events.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
