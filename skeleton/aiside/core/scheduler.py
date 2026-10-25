"""任务与算力调度：单执行道 + 优先级队列 + step 边界抢占 + checkpoint。

模型（PRD FR5 / 方案）：
- 单执行道：同一时刻只跑一个生成/重活任务。
- 优先级：交互任务插队批任务；草稿优先于终稿；批任务可暂停/续跑。
- 抢占：只在 step 边界（job 函数调用 ctx.checkpoint / ctx.is_cancelled），保留 checkpoint。
"""

from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..logging_config import setup_logging
import logging

setup_logging()
logger = logging.getLogger("aiside.scheduler")

# 优先级（数值越小越先）
PRIORITY = {
    "interactive": 0,
    "draft": 10,
    "final": 20,
    "batch": 30,
    "export": 40,
}


class JobCancelled(Exception):
    pass


class JobContext:
    """交给 job 函数的运行上下文：写 checkpoint、检查取消。"""

    def __init__(self, job_id: str, journal, cancel_event: threading.Event):
        self.job_id = job_id
        self._journal = journal
        self._cancel_event = cancel_event

    def checkpoint(self, data: dict) -> None:
        self._journal.checkpoint(self.job_id, data)

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelled(self.job_id)


@dataclass(order=True)
class _QueueItem:
    priority: int
    seq: int
    job_id: str
    func: Any = None  # callable(job_id, ctx)
    node_id: str | None = None


class Scheduler:
    def __init__(self, journal=None):
        self._journal = journal
        self._heap: list[_QueueItem] = []
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._statuses: dict[str, str] = {}

    # ---- 提交 / 取消 ----
    def submit(self, job_id: str, func: Callable[[str, JobContext], Any],
               priority: str | int = "batch", node_id: str | None = None) -> None:
        prio = PRIORITY.get(priority, priority) if isinstance(priority, str) else priority
        with self._lock:
            item = _QueueItem(priority=prio, seq=next(self._seq), job_id=job_id,
                              func=func, node_id=node_id)
            heapq.heappush(self._heap, item)
            self._cancel_events[job_id] = threading.Event()
            self._statuses[job_id] = "queued"
        logger.info("job queued job_id=%s priority=%s", job_id, prio)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            event = self._cancel_events.get(job_id)
        if event is not None:
            event.set()
        logger.info("job cancel requested job_id=%s", job_id)

    def status(self, job_id: str) -> str:
        return self._statuses.get(job_id, "unknown")

    # ---- worker ----
    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._run, name="aiside-scheduler", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._heap:
                    item = None
                else:
                    item = heapq.heappop(self._heap)
                if item is not None:
                    self._statuses[item.job_id] = "running"
            if item is None:
                self._stop.wait(timeout=0.1)
                continue
            self._execute(item)

    def _execute(self, item: _QueueItem) -> None:
        ctx = JobContext(item.job_id, self._journal, self._cancel_events[item.job_id])
        try:
            if ctx.is_cancelled():
                raise JobCancelled(item.job_id)
            if self._journal:
                self._journal.update(item.job_id, "running")
            item.func(item.job_id, ctx)
            with self._lock:
                self._statuses[item.job_id] = "completed"
            if self._journal:
                self._journal.update(item.job_id, "completed")
        except JobCancelled:
            with self._lock:
                self._statuses[item.job_id] = "cancelled"
            if self._journal:
                self._journal.update(item.job_id, "cancelled", error="cancelled at step boundary")
            logger.info("job cancelled job_id=%s", item.job_id)
        except Exception as exc:  # noqa: BLE001 - 记录失败，不静默
            with self._lock:
                self._statuses[item.job_id] = "failed"
            if self._journal:
                self._journal.update(item.job_id, "failed", error=str(exc))
            logger.exception("job failed job_id=%s", item.job_id)
