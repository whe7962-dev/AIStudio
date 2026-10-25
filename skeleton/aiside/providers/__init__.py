"""推理 provider 抽象：local / API 双 provider，正式版切本地，demo 期走豆包 Seedream。

provider 与 stub 走同一接口（ImageProvider），CI 用 stub 录制响应回放，不调真实 API。
"""

from .base import GeneratedImage, ImageProvider
from .stub import StubProvider
from .seedream import SeedreamProvider

__all__ = ["GeneratedImage", "ImageProvider", "StubProvider", "SeedreamProvider"]


def get_provider(settings) -> ImageProvider:
    """按配置选择 provider；demo 期可用 Seedream，默认 stub（离线可跑）。"""
    if settings.provider == "seedream":
        return SeedreamProvider(settings)
    return StubProvider()
