"""Shared memory service dependencies and summary representation."""

from dataclasses import dataclass

from sqlalchemy import select

from zhiyu.core.memory.freshness import needs_confirmation
from zhiyu.core.memory.indexer import sync_changed_index
from zhiyu.core.memory.mutations import FileMutationManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import Memory, MemorySource, Message
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository

@dataclass(slots=True)
class MemorySummary:
    id: str
    type: str
    content: str
    status: str
    origin: str
    shared: bool
    tier: str
    source_message_id: str | None
    source_content: str | None
    source_conversation_id: str | None
    supersedes_id: str | None
    file_path: str | None
    promotion_status: str
    promoted_to_id: str | None
    last_evidence_at: str | None
    confirmation_status: str
    sources: list[dict]

def _summary(db, memory) -> MemorySummary:
    source = db.get(Message, memory.source_message_id) if memory.source_message_id else None
    sources = []
    for link in db.scalars(
        select(MemorySource)
        .where(MemorySource.memory_id == memory.id)
        .order_by(MemorySource.observed_at)
    ):
        source_message = db.get(Message, link.source_message_id) if link.source_message_id else None
        source_memory = db.get(Memory, link.source_memory_id) if link.source_memory_id else None
        sources.append(
            {
                "content": source_message.content if source_message else source_memory.content if source_memory else None,
                "conversation_id": link.conversation_id,
                "observed_at": link.observed_at.isoformat() if link.observed_at else None,
                "source_kind": link.source_kind,
                "trust": link.trust,
            }
        )
    return MemorySummary(
        id=memory.id,
        type=memory.type,
        content=memory.content,
        status=memory.status,
        origin=memory.origin,
        shared=memory.shared,
        tier=memory.tier,
        source_message_id=memory.source_message_id,
        source_content=source.content if source is not None else None,
        source_conversation_id=source.conversation_id if source is not None else None,
        supersedes_id=memory.supersedes_id,
        file_path=memory.file_path,
        promotion_status=memory.promotion_status,
        promoted_to_id=memory.promoted_to_id,
        last_evidence_at=(memory.last_evidence_at or memory.observed_at).isoformat()
        if (memory.last_evidence_at or memory.observed_at)
        else None,
        confirmation_status="needs_confirmation" if needs_confirmation(memory) else "current",
        sources=sources,
    )


class MemoryOperations:
    """Dependencies shared by memory queries and lifecycle operations."""

    def __init__(self, session_factory=SessionLocal, store: MemoryStore | None = None) -> None:
        self.session_factory = session_factory
        self.memories = MemoryRepository()
        self.jobs = MemoryJobRepository()
        self.identities = IdentityRepository()
        self.store = store or MemoryStore()
        self.mutations = FileMutationManager(self.store)

    def _sync(self, db, identity_id: str) -> None:
        sync_changed_index(db, self.store, identity_id)
