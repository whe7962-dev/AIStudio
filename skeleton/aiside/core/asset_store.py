"""内容寻址资产库：按内容哈希去重存储，原始上传素材默认不删除。

存储布局：
  root/blobs/<cid[:2]>/<cid>.bin
  root/meta/<cid[:2]>/<cid>.json
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .ids import content_hash


class AssetStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        self.meta_dir = self.root / "meta"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, cid: str) -> Path:
        return self.blob_dir / cid[:2] / f"{cid}.bin"

    def _meta_path(self, cid: str) -> Path:
        return self.meta_dir / cid[:2] / f"{cid}.json"

    def put(self, data: bytes, meta: dict | None = None) -> str:
        cid = content_hash(data)
        blob = self._blob_path(cid)
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(data)
        record = dict(meta or {})
        record.setdefault("cid", cid)
        record.setdefault("size", len(data))
        record["archived"] = record.get("archived", False)
        meta_path = self._meta_path(cid)
        if not meta_path.exists():
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return cid

    def get(self, cid: str) -> bytes:
        blob = self._blob_path(cid)
        if not blob.exists():
            raise KeyError(f"asset not found: {cid}")
        return blob.read_bytes()

    def meta(self, cid: str) -> dict:
        meta_path = self._meta_path(cid)
        if not meta_path.exists():
            return {"cid": cid}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def exists(self, cid: str) -> bool:
        return self._blob_path(cid).exists()

    def list(self) -> list[dict]:
        result = []
        for meta_path in self.meta_dir.glob("*/*.json"):
            result.append(json.loads(meta_path.read_text(encoding="utf-8")))
        return result

    def archive(self, cid: str) -> None:
        """归档：标记但不删除原始数据（原始上传素材默认不删除）。"""
        record = self.meta(cid)
        record["archived"] = True
        meta_path = self._meta_path(cid)
        meta_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def purge(self, cid: str) -> None:
        """显式删除（仅归档后允许；破坏性操作，调用方负责权限确认）。"""
        self._blob_path(cid).unlink(missing_ok=True)
        self._meta_path(cid).unlink(missing_ok=True)
