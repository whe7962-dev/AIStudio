"""ID 与内容寻址工具函数。"""

from __future__ import annotations

import hashlib
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
