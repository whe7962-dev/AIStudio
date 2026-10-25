import base64

from aiside.providers.seedream import SeedreamProvider
from aiside.providers.stub import StubProvider


def test_stub_provider_generates_png_and_deterministic():
    p = StubProvider()
    img1 = p.generate(prompt="x", seed=5)
    img2 = p.generate(prompt="x", seed=5)
    img3 = p.generate(prompt="x", seed=6)
    assert img1.data.startswith(b"\x89PNG")
    assert img1.data == img2.data
    assert img1.data != img3.data


class _S:
    demo_base_url = "https://ark.cn-beijing.volces.com"
    demo_api_key = "secret"
    demo_model_draft = "draft-model"
    demo_model_final = "final-model"
    demo_model_edit = "edit-model"


def test_seedream_pick_model_and_extract_url(monkeypatch):
    p = SeedreamProvider(_S())
    assert p._pick_model("draft") == "draft-model"
    assert p._pick_model("final") == "final-model"
    assert p._pick_model("inpaint") == "edit-model"

    class _FakeResp:
        content = b"downloaded-bytes"
        def raise_for_status(self):
            return None

    monkeypatch.setattr("aiside.providers.seedream.httpx.get",
                        lambda url, timeout: _FakeResp())
    data = {"data": [{"url": "http://x/img.png", "content_filter": {}}]}
    import httpx
    resp = httpx.Response(200, request=httpx.Request("POST", "http://x"), json=data)
    image_data, meta = p._extract_image(data, resp)
    assert meta["content_filter"] == {}
    assert image_data == b"downloaded-bytes"


def test_seedream_extract_b64():
    p = SeedreamProvider(_S())
    payload = base64.b64encode(b"png-bytes").decode("ascii")
    data = {"data": [{"b64_json": payload}]}
    import httpx
    resp = httpx.Response(200, request=httpx.Request("POST", "http://x"), json=data)
    image_data, _ = p._extract_image(data, resp)
    assert image_data == b"png-bytes"
