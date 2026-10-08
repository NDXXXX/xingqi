"""Incremental synchronization of externally changed memory files."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory, MemoryEmbedding, MemoryFileIndex, MemoryMutation
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.memory.mutations import FileMutationManager
from zhiyu.core.memory.retriever import derive_trigger_text
from zhiyu.core.memory.store import CORE_FILE, IDENTITY_FILE, USER_FILE, MemoryStore
from zhiyu.core.memory.index_common import _entries_with_keys, _save_file_index


def sync_changed_index(
    db: Session, store: MemoryStore, identity_id: str | None = None
) -> dict[str, int]:
    """只解析文件元数据变化的记忆文件；全量校准仍由 rebuild_index 提供。"""
    identity_id = identity_id or IdentityRepository().local(db).id
    repo = MemoryRepository()
    mutations = FileMutationManager(store)
    mutations.recover_prepared(db, identity_id)
    incomplete = db.scalars(
        select(MemoryMutation.id).where(
            MemoryMutation.identity_id == identity_id,
            MemoryMutation.status == "file_applied",
        )
    ).first()
    if incomplete is not None:
        from zhiyu.core.memory.index_rebuild import rebuild_index

        return rebuild_index(db, store, identity_id)
    files = {store.relative_path(path): path for path in store.list_memory_files(identity_id)}
    snapshots = {
        row.file_path: row
        for row in db.scalars(
            select(MemoryFileIndex).where(MemoryFileIndex.identity_id == identity_id)
        )
    }
    changed = []
    present = set()
    for relative, path in files.items():
        if not path.exists():
            continue
        present.add(relative)
        stat = path.stat()
        snapshot = snapshots.get(relative)
        if snapshot is None or snapshot.file_size != stat.st_size or snapshot.mtime_ns != stat.st_mtime_ns:
            changed.append((relative, path))

    stats = {"files_scanned": len(files), "files_changed": 0, "created": 0, "updated": 0, "invalidated": 0}
    for relative, path in changed:
        keyed_entries = _entries_with_keys(store, path)
        entries = {key: entry for key, entry in keyed_entries}
        tier = "core" if path.name in (IDENTITY_FILE, USER_FILE, CORE_FILE) else "episodic"
        rows = db.scalars(
            select(Memory).where(
                Memory.identity_id == identity_id, Memory.file_path == relative
            )
        ).all()
        by_key = {row.entry_key: row for row in rows if row.entry_key}
        for key, entry in entries.items():
            row = by_key.get(key)
            if row is None:
                row = repo.create(
                    db,
                    type=entry.meta.get("type", "fact"),
                    content=entry.content,
                    identity_id=identity_id,
                    origin="manual" if tier == "core" else "automatic",
                    tier=tier,
                    trust="imported",
                    source_kind="import",
                    trigger_text=(derive_trigger_text(entry.content) if tier == "core" else None),
                    promotion_status="none" if tier == "core" else "pending",
                    file_path=relative,
                    line_start=entry.line_start,
                    line_end=entry.line_end,
                    content_hash=entry.hash,
                    entry_key=key,
                )
                stats["created"] += 1
                continue
            if row.content_hash != entry.hash:
                db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == row.id))
                repo.update(
                    db,
                    row,
                    origin="manual",
                    trust="imported",
                    source_kind="import",
                    source_message_id=None,
                    conversation_id=None,
                    promotion_status="none" if tier == "core" else "pending",
                    promoted_to_id=None,
                    last_evidence_at=None,
                )
            repo.update(
                db,
                row,
                content=entry.content,
                type=entry.meta.get("type", row.type),
                line_start=entry.line_start,
                line_end=entry.line_end,
                content_hash=entry.hash,
                trigger_text=(derive_trigger_text(entry.content) if tier == "core" else None),
            )
            stats["updated"] += 1
        for row in rows:
            if row.entry_key in entries or row.status != "active":
                continue
            db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == row.id))
            repo.update(db, row, status="invalidated", file_path=None, line_start=None, line_end=None, content_hash=None)
            stats["invalidated"] += 1
        _save_file_index(db, store, identity_id, path)
        stats["files_changed"] += 1

    for relative, snapshot in snapshots.items():
        if relative in present or not store.is_managed_path(identity_id, store.resolve_relative(relative)):
            continue
        rows = db.scalars(
            select(Memory).where(
                Memory.identity_id == identity_id,
                Memory.file_path == relative,
                Memory.status == "active",
            )
        ).all()
        for row in rows:
            db.execute(delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == row.id))
            repo.update(db, row, status="invalidated", file_path=None, line_start=None, line_end=None, content_hash=None)
            stats["invalidated"] += 1
        db.delete(snapshot)
    live_paths = {
        store.relative_path(path)
        for path in store.list_memory_files(identity_id)
        if path.exists()
    }
    for snapshot in db.scalars(
        select(MemoryFileIndex).where(MemoryFileIndex.identity_id == identity_id)
    ).all():
        if snapshot.file_path not in live_paths:
            db.delete(snapshot)
    db.commit()
    return stats
