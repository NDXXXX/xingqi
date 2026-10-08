"""Compatibility entry point for the memory application service."""

from __future__ import annotations

from zhiyu.application.memory_lifecycle import MemoryLifecycleService
from zhiyu.application.memory_queries import MemoryQueryService
from zhiyu.application.memory_shared import MemorySummary
from zhiyu.core.memory.indexer import get_index_status, rebuild_index
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository


class MemoryService:
    """Expose the established memory service API across focused modules."""

    def __init__(
        self,
        session_factory=SessionLocal,
        store: MemoryStore | None = None,
    ) -> None:
        shared_store = store or MemoryStore()
        self.session_factory = session_factory
        self.store = shared_store
        self._queries = MemoryQueryService(session_factory, shared_store)
        self._lifecycle = MemoryLifecycleService(session_factory, shared_store)

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
            return get_index_status(db)

    def consolidation_runs(self, limit: int = 5) -> list[dict]:
        return self._queries.consolidation_runs(limit)

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

    def rebuild_index(self) -> dict:
        with self.session_factory() as db:
            return rebuild_index(db, self.store)

    def export_files(self) -> list[tuple[str, str]]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().local(db).id
        return [
            (path.name, path.read_text(encoding="utf-8"))
            for path in self.store.list_memory_files(identity_id)
            if path.exists()
        ]
