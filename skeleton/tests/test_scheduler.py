import time

from aiside.core.job_journal import JobJournal
from aiside.core.scheduler import Scheduler


def test_priority_order():
    s = Scheduler()
    order = []
    s.submit("low", lambda jid, ctx: order.append("low"), priority="batch")
    s.submit("high", lambda jid, ctx: order.append("high"), priority="interactive")
    s.start()
    deadline = time.time() + 2
    while len(order) < 2 and time.time() < deadline:
        time.sleep(0.05)
    s.stop()
    assert order == ["high", "low"]


def test_cancel_at_step_boundary(tmp_path):
    journal = JobJournal(tmp_path / "journal.sqlite3")
    s = Scheduler(journal=journal)
    journal.record("j1", "generate", {"count": 10})

    def job(job_id, ctx):
        for step in range(100):
            ctx.raise_if_cancelled()
            ctx.checkpoint({"step": step})
            time.sleep(0.01)

    s.submit("j1", job, priority="draft")
    s.start()
    time.sleep(0.05)
    s.cancel("j1")
    deadline = time.time() + 3
    while s.status("j1") not in {"cancelled", "completed", "failed"} and time.time() < deadline:
        time.sleep(0.05)
    s.stop()
    assert s.status("j1") == "cancelled"
    assert journal.get("j1")["status"] == "cancelled"


def test_failed_job_recorded(tmp_path):
    journal = JobJournal(tmp_path / "journal.sqlite3")
    s = Scheduler(journal=journal)
    journal.record("j2", "generate", {})

    def boom(job_id, ctx):
        raise RuntimeError("boom")

    s.submit("j2", boom, priority="draft")
    s.start()
    deadline = time.time() + 2
    while s.status("j2") != "failed" and time.time() < deadline:
        time.sleep(0.05)
    s.stop()
    assert journal.get("j2")["status"] == "failed"
    assert "boom" in journal.get("j2")["error"]
