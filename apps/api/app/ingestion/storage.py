"""Object storage for original and generated documents.

Originals are content-addressed and write-once: a key that already exists is
never rewritten, so an ingested file cannot be mutated in place.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from ..config import get_settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ImmutableObjectError(RuntimeError):
    """Raised on an attempt to overwrite a stored original."""


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes, *, immutable: bool = True) -> str: ...

    def get(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...


class LocalObjectStore:
    """Filesystem-backed store. Swap for S3 by implementing :class:`ObjectStore`."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else get_settings().storage_root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Reject traversal outright rather than normalizing it away.
        candidate = (self.root / key).resolve()
        root = self.root.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"storage key escapes the storage root: {key!r}")
        return candidate

    def put(self, key: str, data: bytes, *, immutable: bool = True) -> str:
        path = self._path(key)
        if path.exists():
            if immutable:
                existing = path.read_bytes()
                if existing != data:
                    raise ImmutableObjectError(
                        f"refusing to overwrite stored object at {key!r} with different bytes"
                    )
                return key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def document_key(case_id: str, sha256: str, filename: str) -> str:
    suffix = Path(filename).suffix.lower()[:10]
    return f"cases/{case_id}/documents/{sha256}{suffix}"


def artifact_key(case_id: str, demand_id: str, filename: str) -> str:
    return f"cases/{case_id}/demands/{demand_id}/{filename}"


_default_store: LocalObjectStore | None = None


def get_object_store() -> LocalObjectStore:
    global _default_store
    if _default_store is None:
        _default_store = LocalObjectStore()
    return _default_store
