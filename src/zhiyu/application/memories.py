"""Compatibility entry point for the memory application service."""

from __future__ import annotations

from zhiyu.application.memory_lifecycle import MemoryLifecycleService
from zhiyu.application.memory_queries import MemoryQueryService
from zhiyu.application.memory_shared import MemorySummary
from zhiyu.core.memory.indexer import get_index_status, rebuild_index
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import SessionLocal
from sqlalchemy import delete
from zhiyu.infrastructure.database.models import MemoryConsolidationRun, utcnow
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository


class MemoryService:
    """Expose the established memory service API across focused modules."""

    def __init__(
        self,
        session_factory=SessionLocal,
        store: MemoryStore | None = None,
        character_id: str | None = None,
    ) -> None:
        shared_store = store or MemoryStore()
        self.session_factory = session_factory
        self.character_id = character_id
        self.store = shared_store
        self._queries = MemoryQueryService(session_factory, shared_store, character_id)
        self._lifecycle = MemoryLifecycleService(session_factory, shared_store, character_id)

    def list(
        self, *, include_inactive: bool = False, tier: str | None = None
    ) -> list[MemorySummary]:
        return self._queries.list(include_inactive=include_inactive, tier=tier)

    def search(
        self, query: str, *, include_inactive: bool = False, tier: str | None = None
    ) -> list[MemorySummary]:
        return self._queries.search(query, include_inactive=include_inactive, tier=tier)

    def get(self, memory_id: str) -> MemorySummary | None:
        return self._queries.get(memory_id)

    def recall_explain(self, query: str) -> dict:
        return self._queries.recall_explain(query)

    def status(self) -> dict[str, int | str]:
        return self._queries.status()

    def index_status(self) -> dict:
        with self.session_factory() as db:
            return get_index_status(db, IdentityRepository().for_agent(db, self.character_id).id)

    def consolidation_runs(self, limit: int = 5, offset: int = 0) -> list[dict]:
        return self._queries.consolidation_runs(limit, offset)

    def add(self, *, type: str, content: str) -> MemorySummary:
        return self._lifecycle.add(type=type, content=content)

    def confirm(self, memory_id: str) -> MemorySummary:
        return self._lifecycle.confirm(memory_id)

    def keep(self, memory_id: str) -> MemorySummary:
        return self._lifecycle.keep(memory_id)

    def edit(self, memory_id: str, *, content: str) -> MemorySummary:
        return self._lifecycle.edit(memory_id, content=content)

    def complete(self, memory_id: str) -> MemorySummary:
        return self._lifecycle.complete(memory_id)

    def forget(self, memory_id: str) -> None:
        self._lifecycle.forget(memory_id)

    def plan_forget(
        self,
        *,
        memory_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        return self._lifecycle.plan_forget(
            memory_id=memory_id, conversation_id=conversation_id
        )

    def forget_conversation(self, conversation_id: str) -> int:
        return self._lifecycle.forget_conversation(conversation_id)

    def clear(self) -> int:
        with self.session_factory() as db:
            identity = IdentityRepository().for_agent(db, self.character_id)
            identity_id = identity.id
            identity.memory_reset_at = utcnow()
            self._lifecycle.jobs.cancel_pending(db, identity.id)
            db.commit()
        items = self.list(include_inactive=True)
        for item in items:
            if self.get(item.id) is not None:
                self.forget(item.id)
        self.store.clear_dreams(identity_id)
        with self.session_factory() as db:
            db.execute(delete(MemoryConsolidationRun).where(MemoryConsolidationRun.identity_id == identity_id))
            db.commit()
        return len(items)

    def rebuild_index(self) -> dict:
        with self.session_factory() as db:
            return rebuild_index(db, self.store, IdentityRepository().for_agent(db, self.character_id).id)

    def export_files(self) -> list[tuple[str, str]]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().for_agent(db, self.character_id).id
        return [
            (path.name, path.read_text(encoding="utf-8"))
            for path in self.store.list_memory_files(identity_id)
            if path.exists()
        ]
