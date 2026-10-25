import io
import zipfile

from PIL import Image

from aiside import demo


def _img_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 100)).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (100, 200, 100)).save(buf, format="JPEG")
    return buf.getvalue()


def _fake_cutout() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(img).ellipse([20, 20, 180, 180], fill=(255, 255, 255, 255))
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeSeedream:
    name = "seedream"

    def inpaint(self, **kw):
        class _G:
            data = _jpeg_bytes()
        return _G()


class _BoomProvider:
    name = "seedream"

    def inpaint(self, **kw):
        raise RuntimeError("boom")


class _RecordingSeedream:
    name = "seedream"

    def __init__(self):
        self.strengths = []
        self.sizes = []

    def inpaint(self, **kw):
        self.strengths.append(kw.get("strength"))
        self.sizes.append(kw.get("size"))
        class _G:
            data = _jpeg_bytes()
        return _G()


class _OfflineProvider:
    name = "stub"


def _make_app(tmp_path, provider):
    from fastapi import FastAPI

    from aiside.demo import router
    from aiside.settings import ROOT_DIR, Settings

    app = FastAPI()
    app.state.settings = Settings(data_dir=tmp_path / "data",
                                  config_dir=ROOT_DIR / "config", provider="stub")
    app.state.provider = provider
    app.include_router(router)
    return app


def test_scene_images_seededit():
    result = demo.generate_scene_images(_FakeSeedream(), _img_bytes(), "p", "studio", 4)
    assert len(result["images"]) == 4
    assert result["failed"] == 0
    assert all(i["status"] == "success" and i["source"] == "seedream" for i in result["images"])


def test_scene_images_count_8():
    result = demo.generate_scene_images(_FakeSeedream(), _img_bytes(), "p", "studio", 8)
    assert len(result["images"]) == 8


def test_scene_images_passes_strength_and_size():
    rec = _RecordingSeedream()
    result = demo.generate_scene_images(rec, _img_bytes(), "p", "studio", 2,
                                        reference_strength=0.3, size="1536x1536")
    assert rec.strengths == [0.3, 0.3]
    assert rec.sizes == ["1536x1536", "1536x1536"]
    assert result["reference_strength"] == 0.3


def test_scene_images_failed_is_retryable():
    result = demo.generate_scene_images(_BoomProvider(), _img_bytes(), "p", "studio", 2)
    assert result["failed"] == 2
    assert all(i["status"] == "failed" and i.get("error") for i in result["images"])


def test_scene_images_offline_local(monkeypatch):
    monkeypatch.setattr(demo, "_cutout", lambda raw: _fake_cutout())
    result = demo.generate_scene_images(_OfflineProvider(), _img_bytes(), "p", "studio", 2)
    assert result["failed"] == 0
    assert all(i["source"] == "local" for i in result["images"])


def _wait_job(client, job_id, timeout=15.0):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = client.get(f"/api/demo/jobs/{job_id}").json()
        if d["status"] in {"success", "partial", "failed", "canceled"}:
            return d
        time.sleep(0.05)
    raise TimeoutError(job_id)


def test_demo_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(demo, "_cutout", lambda raw: _fake_cutout())
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    resp = client.post(
        "/api/demo/generate",
        files=[("images", ("a.png", _img_bytes(), "image/png"))],
        data={"prompt": "p", "scene": "studio", "count": "4", "size": "1024x1024"},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    data = _wait_job(client, job_id)
    assert data["status"] == "success"
    assert len(data["images"]) == 4
    out = tmp_path / "data" / "demo" / job_id
    assert (out / "manifest.json").exists()
    assert (out / "manifest.csv").exists()
    assert len(list(out.glob("sku_studio_*_1024x1024.jpg"))) == 4


def test_export_endpoint_zip(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    gen = client.post(
        "/api/demo/generate",
        files=[("images", ("a.png", _img_bytes(), "image/png"))],
        data={"prompt": "p", "scene": "studio", "count": "2"},
    ).json()
    _wait_job(client, gen["job_id"])
    resp = client.get("/api/demo/export", params={"session_id": gen["job_id"]})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert "manifest.json" in names
    assert "manifest.csv" in names
    assert "sku_studio_1_1024x1024.jpg" in names
    assert "sku_studio_2_1024x1024.jpg" in names


def test_job_retry_failed(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(tmp_path, _BoomProvider()))
    gen = client.post(
        "/api/demo/generate",
        files=[("images", ("a.png", _img_bytes(), "image/png"))],
        data={"prompt": "p", "scene": "studio", "count": "2"},
    ).json()
    data = _wait_job(client, gen["job_id"])
    assert data["status"] == "failed"
    # 用会失败的 provider 重试，接口仍应返回 retried 数量（重试机制本身可用）
    resp = client.post(f"/api/demo/jobs/{gen['job_id']}/retry", json={"indices": [0]})
    assert resp.status_code == 200
    assert resp.json()["retried"] == 1


def test_presets_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    resp = client.get("/api/demo/presets")
    assert resp.status_code == 200
    presets = resp.json()["presets"]
    assert len(presets) >= 6
    assert any(p["id"] == "studio" for p in presets)
    assert all(p["thumb"].startswith("data:image/png;base64,") for p in presets)


def _submit(client, count=1, **data):
    response = client.post('/api/demo/generate',
        files=[('images', ('a.png', _img_bytes(), 'image/png'))],
        data={'prompt': '商品场景图', 'count': count, **data})
    assert response.status_code == 200, response.text
    return response.json()['job_id']


def test_new_seeds_change_each_time_and_same_seed_survives_restart(tmp_path):
    from fastapi.testclient import TestClient
    app = _make_app(tmp_path, _FakeSeedream())
    client = TestClient(app)
    jid = _submit(client, seed_base=123)
    seeds = [_wait_job(client, jid)['images'][0]['seed']]
    for _ in range(3):
        assert client.post(f'/api/demo/jobs/{jid}/retry', json={'indices': [0]}).status_code == 200
        seeds.append(_wait_job(client, jid)['images'][0]['seed'])
    assert len(set(seeds)) == 4
    demo._JOBS.pop(jid)
    restored = client.get(f'/api/demo/jobs/{jid}').json()
    assert restored['can_retry'] and restored['images'][0]['seed'] == seeds[-1]
    assert client.get(restored['reference_url']).content == _img_bytes()
    client.post(f'/api/demo/jobs/{jid}/retry', json={'indices': [0], 'seed_mode': 'same'})
    assert _wait_job(client, jid)['images'][0]['seed'] == seeds[-1]


def test_cancel_stops_queued_images_and_keeps_inflight_successes(tmp_path):
    import threading
    from fastapi.testclient import TestClient
    class BlockingProvider(_FakeSeedream):
        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0
            self.lock = threading.Lock()
        def inpaint(self, **kw):
            with self.lock:
                self.calls += 1
                if self.calls == demo.MAX_PARALLEL:
                    self.started.set()
            assert self.release.wait(5)
            return super().inpaint(**kw)
    provider = BlockingProvider()
    client = TestClient(_make_app(tmp_path, provider))
    jid = _submit(client, count=8)
    try:
        assert provider.started.wait(3)
        assert client.post(f'/api/demo/jobs/{jid}/cancel').json()['status'] == 'canceling'
        assert client.post(f'/api/demo/jobs/{jid}/retry', json={}).status_code == 409
    finally:
        provider.release.set()
    result = _wait_job(client, jid)
    assert result['status'] == 'canceled'
    assert result['succeeded'] == demo.MAX_PARALLEL == provider.calls
    assert sum(x['status'] == 'canceled' for x in result['images']) == 8 - demo.MAX_PARALLEL
    archive = zipfile.ZipFile(io.BytesIO(client.get('/api/demo/export', params={'session_id': jid}).content))
    assert len([n for n in archive.namelist() if n.endswith('.jpg')]) == demo.MAX_PARALLEL
    assert 'reference.bin' not in archive.namelist()


def test_failed_redraw_does_not_export_stale_file(tmp_path):
    from fastapi.testclient import TestClient
    app = _make_app(tmp_path, _FakeSeedream())
    client = TestClient(app)
    jid = _submit(client, count=2)
    initial = _wait_job(client, jid)
    stale = initial['images'][0]['filename']
    app.state.provider = _BoomProvider()
    client.post(f'/api/demo/jobs/{jid}/retry', json={'indices': [0]})
    final = _wait_job(client, jid)
    assert final['status'] == 'partial' and final['succeeded'] == 1
    result = client.get('/api/demo/export', params={'session_id': jid})
    archive = zipfile.ZipFile(io.BytesIO(result.content))
    assert stale not in archive.namelist()
    assert len(archive.namelist()) == 3
    import json
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['files'] == [final['images'][1]['filename']]


def test_history_and_export_after_memory_cleared(tmp_path):
    from fastapi.testclient import TestClient
    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    jid = _submit(client, sku='../../商品 A')
    result = _wait_job(client, jid)
    assert result['images'][0]['filename'].startswith('商品_A_')
    demo._JOBS.pop(jid)
    history = client.get('/api/demo/jobs').json()['jobs']
    assert any(j['job_id'] == jid and j['succeeded'] == 1 for j in history)
    assert client.get('/api/demo/export', params={'session_id': jid}).status_code == 200
    assert client.get('/api/demo/export', params={'session_id': '../' + jid}).status_code == 404


def test_interrupted_job_recovers_completed_results_and_can_retry(tmp_path):
    import json
    from fastapi.testclient import TestClient
    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    jid = _submit(client, count=2)
    _wait_job(client, jid)
    demo._JOBS.pop(jid)
    path = tmp_path / 'data' / 'demo' / jid / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['status'] = 'generating'
    manifest['images'][1] = None
    path.write_text(json.dumps(manifest))
    result = client.get(f'/api/demo/jobs/{jid}').json()
    assert result['status'] == 'interrupted' and result['succeeded'] == 1
    assert result['images'][1]['status'] == 'interrupted'
    client.post(f'/api/demo/jobs/{jid}/retry', json={})
    assert _wait_job(client, jid)['status'] == 'success'


def test_retry_returns_before_provider_finishes_and_rejects_duplicates(tmp_path):
    import threading
    from fastapi.testclient import TestClient
    app = _make_app(tmp_path, _FakeSeedream())
    client = TestClient(app)
    jid = _submit(client)
    _wait_job(client, jid)
    release = threading.Event()
    class SlowProvider(_FakeSeedream):
        def inpaint(self, **kw):
            assert release.wait(5)
            return super().inpaint(**kw)
    app.state.provider = SlowProvider()
    try:
        result = client.post(f'/api/demo/jobs/{jid}/retry', json={'indices': [0, 0]})
        assert result.json()['retried'] == 1 and not release.is_set()
        assert client.post(f'/api/demo/jobs/{jid}/retry', json={'indices': [0]}).status_code == 409
    finally:
        release.set()
    assert _wait_job(client, jid)['status'] == 'success'


def test_generation_validates_inputs_before_starting(tmp_path):
    from fastapi.testclient import TestClient
    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    for data in [{'size': '0x0'}, {'count': '3'}, {'seed_base': '-1'}, {'primary_index': '7'}, {'prompt': ' '}]:
        response = client.post('/api/demo/generate',
            files=[('images', ('a.png', _img_bytes(), 'image/png'))],
            data={'prompt': 'test', **data})
        assert response.status_code == 400
    response = client.post('/api/demo/generate', files=[('images', ('a.png', b'not an image', 'image/png'))], data={'prompt': 'test'})
    assert response.status_code == 400
    assert client.get('/api/demo/jobs').json()['jobs'] == []


def test_legacy_export_without_image_metadata_is_recovered(tmp_path):
    import json
    from fastapi.testclient import TestClient
    client = TestClient(_make_app(tmp_path, _FakeSeedream()))
    directory = tmp_path / 'data' / 'demo' / '0123456789'
    directory.mkdir(parents=True)
    (directory / 'img_0.jpg').write_bytes(_jpeg_bytes())
    (directory / 'cutout.png').write_bytes(_img_bytes())
    (directory / 'manifest.json').write_text(json.dumps({'session_id': '0123456789',
        'provider': 'seedream', 'files': ['cutout.png', 'img_0.jpg']}))
    result = client.get('/api/demo/jobs/0123456789').json()
    assert result['status'] == 'success' and result['succeeded'] == 1
    assert result['can_retry'] is False
    assert client.post('/api/demo/jobs/0123456789/retry', json={}).status_code == 409
    archive = zipfile.ZipFile(io.BytesIO(client.get('/api/demo/export', params={'session_id': '0123456789'}).content))
    assert 'img_0.jpg' in archive.namelist() and 'cutout.png' not in archive.namelist()
