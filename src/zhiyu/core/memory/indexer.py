"""Stable public imports and health state for memory index synchronization."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.core.memory.index_rebuild import rebuild_index as _rebuild_index
from zhiyu.core.memory.index_sync import sync_changed_index as _sync_changed_index
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.models import MemoryFileIndex
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository


_STATUS_PREFIX = "memory_index_status:"
_settings = SettingRepository()
_identities = IdentityRepository()


def _key(identity_id: str) -> str:
    return f"{_STATUS_PREFIX}{identity_id}"


def _read_status(db: Session, identity_id: str) -> dict:
    status = _settings.get(db, _key(identity_id))
    if status is not None:
        return status
    indexed = db.scalars(
        select(MemoryFileIndex.id).where(MemoryFileIndex.identity_id == identity_id)
    ).first() is not None
    return {
        "status": "ready" if indexed else "not_indexed",
        "last_success_at": None,
        "updated_at": None,
        "error": None,
    }


def get_index_status(db: Session, identity_id: str | None = None) -> dict:
    identity_id = identity_id or _identities.local(db).id
    return _read_status(db, identity_id)


def _save_status(
    db: Session,
    identity_id: str,
    status: str,
    *,
    error: str | None = None,
    succeeded: bool = False,
) -> None:
    previous = _read_status(db, identity_id)
    now = datetime.now(timezone.utc).isoformat()
    _settings.set(
        db,
        _key(identity_id),
        {
            "status": status,
            "last_success_at": now if succeeded else previous.get("last_success_at"),
            "updated_at": now,
            "error": error,
        },
    )


def _run(
    operation,
    db: Session,
    store: MemoryStore,
    identity_id: str | None,
    *,
    force_success: bool = False,
):
    resolved_identity = identity_id or _identities.local(db).id
    previous = _read_status(db, resolved_identity)
    if previous["status"] != "ready":
        _save_status(db, resolved_identity, "indexing")
    try:
        result = operation(db, store, resolved_identity)
    except Exception as exc:
        db.rollback()
        state = "stale" if previous.get("last_success_at") else "failed"
        _save_status(
            db,
            resolved_identity,
            state,
            error=f"索引同步失败（{type(exc).__name__}）",
        )
        raise
    if force_success or previous["status"] != "ready" or result.get("files_changed", 0):
        _save_status(db, resolved_identity, "ready", succeeded=True)
    return result


def rebuild_index(db: Session, store: MemoryStore, identity_id: str | None = None):
    return _run(_rebuild_index, db, store, identity_id, force_success=True)


def sync_changed_index(db: Session, store: MemoryStore, identity_id: str | None = None):
    return _run(_sync_changed_index, db, store, identity_id)


__all__ = ["get_index_status", "rebuild_index", "sync_changed_index"]
