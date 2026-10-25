import time

from PIL import Image


def _sample(tmp_path):
    img = Image.new("RGB", (512, 512), (200, 180, 160))
    p = tmp_path / "s.png"
    img.save(p)
    return [str(p)]


def _anchor(workspace, tmp_path):
    ctx = workspace.create_project()
    ingest = workspace.dispatcher.dispatch(
        "ingest_and_qa_photos", {"image_paths": _sample(tmp_path)}, ctx)
    anchor = workspace.dispatcher.dispatch(
        "build_consistency_anchor",
        {"photo_ids": [r["source_asset_id"] for r in ingest["items"]]}, ctx)
    return ctx, anchor["anchor_asset_id"]


def _wait(workspace, project_id, job_id, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = workspace.job_status(project_id, job_id)
        if status["status"] in {"completed", "degraded", "failed", "cancelled"}:
            return status
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_generate_job_writes_step_checkpoint(workspace, tmp_path):
    ctx, anchor_id = _anchor(workspace, tmp_path)
    project_id = ctx.project.project_id
    res = workspace.submit(
        project_id, "generate_image",
        {"mode": "draft", "prompt": "p", "seed": 5, "count": 3, "anchor_id": anchor_id},
        priority="draft")
    status = _wait(workspace, project_id, res["job_id"])
    assert status["status"] in {"completed", "degraded"}
    record = ctx.journal.get(res["job_id"])
    assert record["checkpoint_json"]["done"] == 3
    assert len(record["checkpoint_json"]["asset_ids"]) == 3


def test_generate_resume_skips_done(workspace, tmp_path):
    ctx, anchor_id = _anchor(workspace, tmp_path)
    params = {"mode": "draft", "prompt": "p", "seed": 7, "count": 3,
              "anchor_id": anchor_id}
    first = workspace.dispatcher.dispatch("generate_image", params, ctx)
    assert len(first["asset_ids"]) == 3

    # 模拟崩溃后重启：内存缓存清空，从 checkpoint(done=2) 续跑
    ctx.cache.clear()
    calls = {"n": 0}
    orig = ctx.provider.generate

    def counting(**kw):
        calls["n"] += 1
        return orig(**kw)

    ctx.provider.generate = counting
    resumed = workspace.dispatcher.dispatch(
        "generate_image",
        {**params, "resume": {"done": 2, "asset_ids": first["asset_ids"][:2]}},
        ctx)
    assert calls["n"] == 1                       # 只补第 3 张
    assert resumed["asset_ids"][:2] == first["asset_ids"][:2]
    assert resumed["asset_ids"] == first["asset_ids"]


def test_scan_and_recover_incomplete(workspace, tmp_path):
    ctx, _ = _anchor(workspace, tmp_path)
    project_id = ctx.project.project_id
    ctx.journal.record("job_x", "generate_image", {"mode": "draft"}, project_id=project_id,
                       status="checkpoint")
    assert any(j["job_id"] == "job_x" for j in workspace.scan_incomplete_jobs())
    assert any(r["job_id"] == "job_x" for r in workspace.recover_incomplete(project_id))
