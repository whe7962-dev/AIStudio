"""轻量指标采集：计数器 + 延迟样本，供 /metrics 与观察层使用。

对齐 PRD 成功指标：草稿/终稿延迟、批次一致性分、导出一次通过率、
任务恢复率、OOM 降级触发次数。骨架阶段用内存结构，接入真实模型后补测。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, int] = defaultdict(int)
        self.latency_samples: dict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] += amount

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            self.latency_samples[name].append(seconds)

    def timed(self, name: str):
        class _Timer:
            def __enter__(self2):
                self2.start = time.monotonic()
                return self2

            def __exit__(self2, *exc):
                self.observe(name, time.monotonic() - self2.start)

        return _Timer()

    def p95(self, name: str) -> float | None:
        with self._lock:
            samples = sorted(self.latency_samples.get(name, []))
        if not samples:
            return None
        idx = int(0.95 * len(samples))
        return samples[min(idx, len(samples) - 1)]

    def snapshot(self) -> dict:
        # 注意：不能持锁调用 self.p95（非可重入锁会死锁）；先拷贝样本再算 p95。
        with self._lock:
            counters = dict(self.counters)
            samples = {k: sorted(v) for k, v in self.latency_samples.items()}
        p95 = {}
        for k, s in samples.items():
            if s:
                idx = int(0.95 * len(s))
                p95[k] = s[min(idx, len(s) - 1)]
        return {"counters": counters, "p95": p95}
