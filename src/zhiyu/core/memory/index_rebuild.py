"""Full memory index rebuild and lifecycle recovery."""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import delete, or_, select

from zhiyu.infrastructure.database.models import (
    ForgottenConversation,
    Memory,
    MemoryEmbedding,
    MemoryFileIndex,
    MemoryMutation,
    MemorySource,
)
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.memory.mutations import FileMutationManager
from zhiyu.core.memory.retriever import derive_trigger_text
from zhiyu.core.memory.store import CORE_FILE, USER_FILE, MemoryStore
from zhiyu.core.memory.index_common import _entries_with_keys, _save_file_index


def rebuild_index(
    db: Session,
    store: MemoryStore,
    identity_id: str | None = None,
) -> dict[str, int]:
    repo = MemoryRepository()
    identity_id = identity_id or IdentityRepository().local(db).id
    mutations = FileMutationManager(store)
    recovered = mutations.recover_prepared(db, identity_id)
    prefix = f"identities/{identity_id}/"
    stats = {
        "backfilled": 0,
        "updated": 0,
        "created": 0,
        "invalidated": 0,
        "mutations_recovered": recovered,
        "mutations_completed": 0,
        "forgotten_pruned": 0,
        "lifecycle_recovered": 0,
    }
    forgotten = set(
        db.scalars(
            select(ForgottenConversation.conversation_id).where(
                ForgottenConversation.identity_id == identity_id
            )
        )
    )

    # Move active legacy rows into this identity's vault. Schema upgrade already
    # snapshots the old memory directory; leaving a live global copy would bypass
    # identity-scoped forgetting and keep deleted personal data in active storage.
    all_owned = repo.list_owned(db, identity_id, statuses=None)
    for memory in all_owned:
        if memory.status != "active":
            continue
        if memory.conversation_id in forgotten:
            mutation = None
            if memory.file_path and memory.entry_key:
                path = store.resolve_relative(memory.file_path)
                if store.is_managed_path(identity_id, path):
                    mutation = mutations.remove(
                        db, identity_id, path, memory.entry_key
                    )
            repo.update(
                db,
                memory,
                status="forgotten",
                file_path=None,
                line_start=None,
                line_end=None,
                content_hash=None,
            )
            if mutation is not None:
                mutations.complete(db, mutation)
            stats["forgotten_pruned"] += 1
            continue
        if memory.file_path and memory.file_path.startswith(prefix) and memory.entry_key:
            continue
        if memory.tier == "episodic":
            path = store.daily_path(memory.observed_at, identity_id)
        else:
            path = store.path_for(memory.type, identity_id)
        legacy_path = (
            store.resolve_relative(memory.file_path)
            if memory.file_path
            else None
        )
        legacy_key = memory.entry_key
        legacy_hash = memory.content_hash
        entry = store.append(
            path,
            memory.content,
            meta={"type": memory.type, "importance": str(memory.importance)},
        )
        repo.update(
            db,
            memory,
            content=entry.content,
            file_path=store.relative_path(path),
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        legacy_files = set(store.list_memory_files())
        if legacy_path is not None and legacy_path in legacy_files:
            if legacy_key:
                store.remove_by_id(legacy_path, legacy_key)
            elif legacy_hash:
                store.remove_by_hash(legacy_path, legacy_hash)
        stats["backfilled"] += 1

    indexed_rows = list(
        db.scalars(
            select(Memory).where(
                Memory.identity_id == identity_id,
                Memory.file_path.startswith(prefix),
            )
        )
    )
    paths = set(store.list_memory_files(identity_id))
    for row in indexed_rows:
        if not row.file_path:
            continue
        path = store.resolve_relative(row.file_path)
        if store.is_managed_path(identity_id, path):
            paths.add(path)

    recovery_contexts: dict[str, dict] = {}
    removal_contexts: dict[str, dict] = {}
    cascade_core_ids: set[str] = set()
    applied_mutations = db.scalars(
        select(MemoryMutation).where(
            MemoryMutation.identity_id == identity_id,
            MemoryMutation.status == "file_applied",
        )
    ).all()
    for mutation in applied_mutations:
        try:
            payload = json.loads(mutation.new_entry_text or "{}")
        except json.JSONDecodeError:
            continue
        context = payload.get("context") or {}
        if mutation.operation == "remove":
            removal_contexts[mutation.entry_key] = context
            cascade_ids = context.get("cascade_core_ids")
            if isinstance(cascade_ids, list):
                cascade_core_ids.update(
                    item for item in cascade_ids if isinstance(item, str)
                )
        elif mutation.operation in ("append", "replace"):
            entry_key = payload.get("meta", {}).get("id")
            if entry_key:
                recovery_contexts[entry_key] = context

    for path in sorted(paths):
        relative = store.relative_path(path)
        keyed_entries = _entries_with_keys(store, path)
        live_keys = {key for key, _ in keyed_entries}
        file_name = path.name
        tier = "core" if file_name in (USER_FILE, CORE_FILE) else "episodic"

        rows = db.scalars(
            select(Memory).where(
                Memory.identity_id == identity_id,
                Memory.file_path == relative,
            )
        ).all()
        row_by_key = {row.entry_key: row for row in rows if row.entry_key}

        for key, entry in keyed_entries:
            row = row_by_key.get(key)
            if row is None:
                context = recovery_contexts.get(key, {})
                row = repo.create(
                    db,
                    type=entry.meta.get("type", "fact"),
                    content=entry.content,
                    identity_id=identity_id,
                    importance=_context_importance(
                        context, entry.meta.get("importance")
                    ),
                    origin=_choice(context.get("origin"), {"manual", "automatic", "legacy"}, "manual"),
                    tier=_choice(context.get("tier"), {"core", "episodic"}, tier),
                    trust=_choice(
                        context.get("trust"),
                        {"owner", "agent", "imported"},
                        "owner" if tier == "core" else "agent",
                    ),
                    source_kind=_choice(
                        context.get("source_kind"),
                        {"manual", "message", "consolidation", "import"},
                        "manual",
                    ),
                    trigger_text=(derive_trigger_text(entry.content) if tier == "core" else None),
                    promotion_status=_choice(
                        context.get("promotion_status"),
                        {"none", "pending", "promoted", "rejected", "deferred"},
                        "none" if tier == "core" else "pending",
                    ),
                    source_message_id=context.get("source_message_id"),
                    conversation_id=context.get("conversation_id"),
                    supersedes_id=context.get("supersedes_id"),
                    file_path=relative,
                    line_start=entry.line_start,
                    line_end=entry.line_end,
                    content_hash=entry.hash,
                    entry_key=key,
                )
                _recover_lineage(db, repo, identity_id, row, context)
                stats["created"] += 1
                continue
            if row.content_hash != entry.hash:
                db.execute(
                    delete(MemoryEmbedding).where(
                        MemoryEmbedding.memory_id == row.id
                    )
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
            if row.entry_key in live_keys:
                continue
            context = removal_contexts.get(row.entry_key, {})
            lifecycle = context.get("lifecycle")
            forgotten_conversation_id = context.get(
                "forgotten_conversation_id"
            )
            if isinstance(forgotten_conversation_id, str):
                exists = db.scalars(
                    select(ForgottenConversation.id).where(
                        ForgottenConversation.identity_id == identity_id,
                        ForgottenConversation.conversation_id
                        == forgotten_conversation_id,
                    )
                ).first()
                if exists is None:
                    db.add(
                        ForgottenConversation(
                            id=str(uuid4()),
                            identity_id=identity_id,
                            conversation_id=forgotten_conversation_id,
                        )
                    )
                db.execute(
                    delete(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        MemorySource.conversation_id
                        == forgotten_conversation_id,
                    )
                )
            if lifecycle == "delete":
                db.execute(
                    delete(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        or_(
                            MemorySource.memory_id == row.id,
                            MemorySource.source_memory_id == row.id,
                        ),
                    )
                )
                repo.delete_owned(db, identity_id, row.id)
                stats["lifecycle_recovered"] += 1
                continue
            fields = {
                "file_path": None,
                "line_start": None,
                "line_end": None,
                "content_hash": None,
            }
            if row.status == "active":
                if lifecycle in {"completed", "superseded", "forgotten"}:
                    fields["status"] = lifecycle
                    stats["lifecycle_recovered"] += 1
                else:
                    fields["status"] = "invalidated"
                    stats["invalidated"] += 1
            db.execute(
                delete(MemoryEmbedding).where(MemoryEmbedding.memory_id == row.id)
            )
            repo.update(db, row, **fields)

    # A source-forget operation may crash after removing the source entry but
    # before removing the automatic core that depended only on it. The source
    # mutation carries the intended cascade IDs so recovery does not lose that
    # edge when it deletes the MemorySource row. Re-check sources here: a core
    # that gained another valid source while recovery was pending must survive.
    for core_id in cascade_core_ids:
        core = repo.get_owned(db, identity_id, core_id)
        if core is None or core.origin != "automatic":
            continue
        remaining_source = db.scalars(
            select(MemorySource.id).where(
                MemorySource.identity_id == identity_id,
                MemorySource.memory_id == core_id,
            )
        ).first()
        legacy_remaining = db.scalars(
            select(Memory.id).where(
                Memory.identity_id == identity_id,
                Memory.tier == "episodic",
                Memory.status == "active",
                Memory.promoted_to_id == core_id,
            )
        ).first()
        if remaining_source is not None or legacy_remaining is not None:
            continue
        mutation = None
        if core.file_path and core.entry_key:
            path = store.resolve_relative(core.file_path)
            if store.is_managed_path(identity_id, path):
                mutation = mutations.remove(
                    db,
                    identity_id,
                    path,
                    core.entry_key,
                    context={"lifecycle": "delete"},
                )
        db.execute(
            delete(MemorySource).where(
                MemorySource.identity_id == identity_id,
                or_(
                    MemorySource.memory_id == core.id,
                    MemorySource.source_memory_id == core.id,
                ),
            )
        )
        repo.delete_owned(db, identity_id, core.id)
        if mutation is not None:
            mutations.complete(db, mutation)
        stats["lifecycle_recovered"] += 1

    for path in paths:
        if path.exists():
            _save_file_index(db, store, identity_id, path)
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
    stats["mutations_completed"] = mutations.reconcile_file_applied(db, identity_id)
    db.commit()
    return stats


def _importance(value: str | None) -> float:
    if value is None:
        return 0.5
    try:
        number = float(value)
    except ValueError:
        return 0.5
    if number > 1.0:
        number /= 10.0
    return max(0.0, min(1.0, number))


def _context_importance(context: dict, fallback: str | None) -> float:
    value = context.get("importance")
    return _importance(str(value) if value is not None else fallback)


def _choice(value, allowed: set[str], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _recover_lineage(db, repo, identity_id: str, memory: Memory, context: dict) -> None:
    supersedes_id = context.get("supersedes_id")
    if isinstance(supersedes_id, str):
        old = repo.get_owned(db, identity_id, supersedes_id)
        if old is not None and old.status == "active":
            repo.update(
                db,
                old,
                status="superseded",
                file_path=None,
                line_start=None,
                line_end=None,
                content_hash=None,
            )

    source_ids = context.get("source_memory_ids")
    if not isinstance(source_ids, list):
        return
    for source_id in source_ids:
        if not isinstance(source_id, str):
            continue
        source = repo.get_owned(db, identity_id, source_id)
        if source is None:
            continue
        exists = db.scalars(
            select(MemorySource.id).where(
                MemorySource.memory_id == memory.id,
                MemorySource.source_memory_id == source.id,
            )
        ).first()
        if exists is None:
            db.add(
                MemorySource(
                    id=str(uuid4()),
                    memory_id=memory.id,
                    identity_id=identity_id,
                    source_memory_id=source.id,
                    source_message_id=source.source_message_id,
                    conversation_id=source.conversation_id,
                    trust=source.trust,
                    source_kind="consolidation",
                    observed_at=source.observed_at,
                )
            )
        repo.update(
            db,
            source,
            promotion_status="promoted",
            promoted_to_id=memory.id,
        )
