"""豆包 Seedream demo provider（火山方舟 Ark）。

仅 demo 期验证链路使用；正式版切本地推理，此 provider 不进入产品方案。
密钥只从 settings（demo-api.env / 环境变量）读取，绝不写进代码或日志。
"""

from __future__ import annotations

import base64
from urllib.parse import urlparse

import httpx

from .base import GeneratedImage


class SeedreamProvider:
    name = "seedream"

    def __init__(self, settings):
        self.base_url = settings.demo_base_url.rstrip("/")
        self.api_key = settings.demo_api_key
        self.model_draft = settings.demo_model_draft
        self.model_final = settings.demo_model_final
        self.model_edit = settings.demo_model_edit

    @property
    def api_base(self) -> str:
        # 兼容两种写法：base_url 可能已经带 /api/v3，也可能只到域名。
        base = self.base_url.rstrip("/")
        if base.endswith("/api/v3"):
            return base
        return f"{base}/api/v3"

    @property
    def network_domain(self) -> str:
        return urlparse(self.base_url).hostname or ""

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _pick_model(self, mode: str) -> str:
        if mode == "final":
            return self.model_final
        if mode == "inpaint":
            return self.model_edit
        return self.model_draft

    def generate(self, *, prompt: str, mode: str = "draft", seed: int = 0,
                 width: int = 1024, height: int = 1024, steps: int = 8,
                 model: str = "", anchor_refs: list[str] | None = None) -> GeneratedImage:
        model = model or self._pick_model(mode)
        body = {
            "model": model,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": "url",
            "seed": seed,
            "watermark": False,
        }
        if anchor_refs:
            body['image'] = anchor_refs[0] if len(anchor_refs) == 1 else anchor_refs
        resp = httpx.post(
            f"{self.api_base}/images/generations",
            headers=self._headers(),
            json=body,
            timeout=120.0,
        )
        data = self._raise_on_error(resp)
        image_data, meta = self._extract_image(data, resp)
        meta.update({"provider": self.name, "model": model, "mode": mode, "seed": seed})
        return GeneratedImage(data=image_data, meta=meta)

    @staticmethod
    def _mime(data: bytes) -> str:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if data[:2] == b"\xff\xd8":
            return "image/jpeg"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        return "image/jpeg"

    def inpaint(self, *, image_data: bytes, mask_data: bytes | None = None, prompt: str,
                seed: int = 0, width: int = 1024, height: int = 1024,
                model: str = "", strength: float | None = None,
                size: str = "1024x1024") -> GeneratedImage:
        # 用户开通的是 doubao-seedream-5-0-flash（支持图生图），走 generations 端点；
        # image 用 data URL 传本地图（Ark 对该模型 image 参数只接受 data URL / URL，不接受裸 base64）。
        model = model or self.model_draft
        image_ref = f"data:{self._mime(image_data)};base64,{base64.b64encode(image_data).decode('ascii')}"
        body = {
            "model": model,
            "prompt": prompt,
            "image": image_ref,
            "response_format": "url",
            "seed": seed,
            "watermark": False,
            "size": size,
        }
        if strength is not None:
            body["strength"] = float(strength)
        resp = httpx.post(
            f"{self.api_base}/images/generations",
            headers=self._headers(),
            json=body,
            timeout=120.0,
        )
        data = self._raise_on_error(resp)
        out_bytes, meta = self._extract_image(data, resp)
        meta.update({"provider": self.name, "model": model, "mode": "i2i", "seed": seed})
        return GeneratedImage(data=out_bytes, meta=meta)

    @staticmethod
    def _raise_on_error(resp: httpx.Response) -> dict:
        if resp.status_code >= 400:
            raise RuntimeError(f"Seedream API {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    @staticmethod
    def _extract_image(data: dict, resp: httpx.Response) -> tuple[bytes, dict]:
        items = data.get("data") or []
        if not items:
            raise RuntimeError(f"Seedream API 无返回图片: {data}")
        item = items[0]
        meta = {"content_filter": item.get("content_filter", {})}
        if item.get("url"):
            img_resp = httpx.get(item["url"], timeout=60.0)
            img_resp.raise_for_status()
            return img_resp.content, meta
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"]), meta
        raise RuntimeError("Seedream API 返回格式无法解析（无 url / b64_json）")
