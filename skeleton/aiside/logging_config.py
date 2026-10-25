"""日志：结构化、脱敏（密钥与素材路径不落明文）。

红线：日志不得包含 API key、不得包含用户素材的原始绝对路径。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

_SENSITIVE_KEYS = {
    "api_key", "apikey", "authorization", "token", "secret", "password",
    "demo_api_key",
}
_REDACT = "***"


def _redact(text: str) -> str:
    # 去除常见密钥形态（key=value / Authorization: Bearer ...）
    text = re.sub(r"(?i)(api_?key|authorization|token|secret)\s*[:=]\s*\S+", r"\1=" + _REDACT, text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return _redact(msg)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("aiside")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)
    root.setLevel(level)
