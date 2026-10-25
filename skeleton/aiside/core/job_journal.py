"""Job journal（SQLite WAL）：记录任务输入、图哈希、参数、checkpoint，支持崩溃续跑。

不把 job journal 暴露为模型可调用工具（见方案：由任务系统内部实现）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

QUEUED = "queued"
RUNNING = "running"
CHECKPOINT = "checkpoint"
COMPLETED = "completed"
FAILED = "failed"
DEGRADED = "degraded"
AWAITING_CONFIRMATION = "awaiting_confirmation"
CANCELLED = "cancelled"

_INCOMPLETE = {QUEUED, RUNNING, CHECKPOINT, AWAITING_CONFIRMATION}


class JobJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                tool TEXT NOT NULL,
                node_id TEXT,
                project_id TEXT,
                params_json TEXT NOT NULL,
                status TEXT NOT NULL,
                checkpoint_json TEXT,
                error TEXT,
                created_at REAL,
                updated_at REAL
            )
            """
        )
        self._conn.commit()

    def _now(self) -> float:
        return time.time()

    def record(self, job_id: str, tool: str, params: dict, node_id: str | None = None,
               project_id: str | None = None, status: str = QUEUED) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                (job_id, tool, node_id, project_id, params_json, status, checkpoint_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (job_id, tool, node_id, project_id, json.dumps(params, ensure_ascii=False), status,
                 self._now(), self._now()),
            )
            self._conn.commit()

    def update(self, job_id: str, status: str, checkpoint: dict | None = None,
               error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE jobs SET status=?, checkpoint_json=COALESCE(?, checkpoint_json),
                    error=COALESCE(?, error), updated_at=? WHERE job_id=?
                """,
                (status,
                 json.dumps(checkpoint, ensure_ascii=False) if checkpoint is not None else None,
                 error, self._now(), job_id),
            )
            self._conn.commit()

    def checkpoint(self, job_id: str, data: dict) -> None:
        self.update(job_id, CHECKPOINT, checkpoint=data)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,))
            row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        return self._row_to_dict(row, cols)

    def recover_incomplete(self) -> list[str]:
        """启动时扫描未完成任务，供续跑（恢复率 100% 的观测点）。"""
        with self._lock:
            cur = self._conn.execute(
                f"SELECT job_id FROM jobs WHERE status IN ({','.join('?' for _ in _INCOMPLETE)})",
                tuple(_INCOMPLETE),
            )
            rows = cur.fetchall()
        return [r[0] for r in rows]

    def _row_to_dict(self, row, cols) -> dict:
        d = dict(zip(cols, row))
        for key in ("params_json", "checkpoint_json"):
            if d.get(key):
                d[key] = json.loads(d[key])
        return d

    def close(self) -> None:
        with self._lock:
            self._conn.close()
