"""Provider 抽象接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class GeneratedImage:
    data: bytes
    meta: dict = field(default_factory=dict)


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    def generate(self, *, prompt: str, mode: str = "draft", seed: int = 0,
                 width: int = 512, height: int = 512, steps: int = 8,
                 model: str = "", anchor_refs: list[str] | None = None) -> GeneratedImage:
        """生成一张图（draft / final / inpaint）。"""
        ...

    def inpaint(self, *, image_data: bytes, mask_data: bytes | None, prompt: str,
                seed: int = 0, width: int = 512, height: int = 512,
                model: str = "") -> GeneratedImage:
        """局部重绘。"""
        ...
