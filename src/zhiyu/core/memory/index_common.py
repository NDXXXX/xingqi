"""Shared helpers for incremental and full memory index synchronization."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import MemoryFileIndex, utcnow
from zhiyu.core.memory.store import Entry, MemoryStore, file_hash


def _derived_key(relative_path: str, entry: Entry, occurrence: int) -> str:
    payload = f"{relative_path}\0{entry.hash}\0{occurrence}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _entries_with_keys(store: MemoryStore, path) -> list[tuple[str, Entry]]:
    relative = store.relative_path(path)
    occurrences: dict[str, int] = defaultdict(int)
    seen: set[str] = set()
    result: list[tuple[str, Entry]] = []
    for entry in store.read_entries(path):
        occurrences[entry.hash] += 1
        key = entry.id or _derived_key(relative, entry, occurrences[entry.hash])
        if key in seen:
            raise ValueError(f"记忆文件包含重复 entry id: {relative}#{key}")
        seen.add(key)
        result.append((key, entry))
    return result


def _save_file_index(db: Session, store: MemoryStore, identity_id: str, path) -> None:
    relative = store.relative_path(path)
    stat = path.stat()
    row = db.scalars(
        select(MemoryFileIndex).where(
            MemoryFileIndex.identity_id == identity_id,
            MemoryFileIndex.file_path == relative,
        )
    ).first()
    if row is None:
        row = MemoryFileIndex(
            id=str(uuid4()), identity_id=identity_id, file_path=relative
        )
        db.add(row)
    row.file_size = stat.st_size
    row.mtime_ns = stat.st_mtime_ns
    row.content_hash = file_hash(path.read_text(encoding="utf-8"))
    row.indexed_at = utcnow()
    row.last_error = None
