"""本地桩 provider：离线生成占位图，用于跑通骨架与单测，不联网、无需密钥。

正式版将替换为 Apple MLX/Core ML 本地推理（FLUX/Qwen-Image）。
"""

from __future__ import annotations

import io
import random

from PIL import Image, ImageDraw

from .base import GeneratedImage


class StubProvider:
    name = "stub"

    def generate(self, *, prompt: str, mode: str = "draft", seed: int = 0,
                 width: int = 512, height: int = 512, steps: int = 8,
                 model: str = "", anchor_refs: list[str] | None = None) -> GeneratedImage:
        rng = random.Random(seed)
        bg = (
            rng.randint(160, 235),
            rng.randint(160, 235),
            rng.randint(160, 235),
        )
        img = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(img)
        # 画一个简单商品占位框
        box_w, box_h = width // 3, height // 3
        left = (width - box_w) // 2
        top = (height - box_h) // 2
        draw.rectangle([left, top, left + box_w, top + box_h],
                       fill=(255, 255, 255), outline=(60, 60, 60), width=max(2, width // 160))
        text = f"stub:{mode}:{seed}"
        draw.text((8, 8), text, fill=(30, 30, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return GeneratedImage(
            data=buf.getvalue(),
            meta={"provider": self.name, "model": model or "stub", "mode": mode,
                  "seed": seed, "width": width, "height": height, "steps": steps},
        )

    def inpaint(self, *, image_data: bytes, mask_data: bytes | None, prompt: str,
                seed: int = 0, width: int = 512, height: int = 512,
                model: str = "") -> GeneratedImage:
        # 骨架阶段：重绘 = 基于原图重新占位（不真改像素），保证链路可跑。
        return self.generate(prompt=prompt, mode="inpaint", seed=seed,
                             width=width, height=height, model=model)
