"""任务规划（对应 s05）：轻量 todo 计划 + 确定性执行。

真实 LLM 循环接入后，todo 由模型维护；骨架阶段由确定性流水线（pipeline.py）驱动，
保证「多步骤、可跟踪、可中断续跑」的结构在无模型时也能跑通。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TodoItem:
    id: str
    title: str
    status: str = "pending"  # pending | in_progress | done | failed
    detail: dict[str, Any] = field(default_factory=dict)


class TodoList:
    def __init__(self) -> None:
        self.items: list[TodoItem] = []

    def add(self, title: str, detail: dict | None = None) -> TodoItem:
        item = TodoItem(id=f"todo_{len(self.items) + 1}", title=title, detail=detail or {})
        self.items.append(item)
        return item

    def start(self, item_id: str) -> None:
        self._get(item_id).status = "in_progress"

    def done(self, item_id: str) -> None:
        self._get(item_id).status = "done"

    def fail(self, item_id: str) -> None:
        self._get(item_id).status = "failed"

    def _get(self, item_id: str) -> TodoItem:
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def summary(self) -> list[dict]:
        return [{"id": i.id, "title": i.title, "status": i.status, "detail": i.detail}
                for i in self.items]
