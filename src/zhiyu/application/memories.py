"""本地用户的记忆查看、纠正和删除用例。手动记忆直接写入长期核心（文件 + 索引）。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from zhiyu.core.memory.extractor import MEMORY_TYPES
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.embedding import embed_and_store
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import ForgottenConversation, Memory, Message, utcnow
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


def _summary(db, memory) -> MemorySummary:
    source = db.get(Message, memory.source_message_id) if memory.source_message_id else None
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
    )


class MemoryService:
    def __init__(self, session_factory=SessionLocal, store: MemoryStore | None = None) -> None:
        self.session_factory = session_factory
        self.memories = MemoryRepository()
        self.jobs = MemoryJobRepository()
        self.identities = IdentityRepository()
        self.store = store or MemoryStore()

    def list(self, *, include_inactive: bool = False, tier: str | None = None) -> list[MemorySummary]:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            statuses = None if include_inactive else ("active",)
            return [
                _summary(db, item)
                for item in self.memories.list_owned(db, identity_id, statuses=statuses, tier=tier)
            ]

    def search(
        self, query: str, *, include_inactive: bool = False, tier: str | None = None
    ) -> list[MemorySummary]:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("搜索内容不能为空")
        return [
            item
            for item in self.list(include_inactive=include_inactive, tier=tier)
            if needle in item.content.lower()
        ]

    def get(self, memory_id: str) -> MemorySummary | None:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            memory = self.memories.get_owned(db, identity_id, memory_id)
            return _summary(db, memory) if memory is not None else None

    def add(self, *, type: str, content: str) -> MemorySummary:
        memory_type, normalized = self._validate(type, content)
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            memory = self._create_core(db, identity_id, memory_type, normalized)
            db.commit()
            return _summary(db, memory)

    def edit(self, memory_id: str, *, content: str) -> MemorySummary:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            old = self.memories.get_owned(db, identity_id, memory_id)
            if old is None:
                raise ValueError("记忆不存在")
            if old.status != "active":
                raise ValueError("只能修改有效记忆")
            _, normalized = self._validate(old.type, content)
            self.jobs.cancel_pending(db, identity_id)
            try:
                self._remove_from_file(old)
                self.memories.update(
                    db,
                    old,
                    status="superseded",
                    updated_at=utcnow(),
                    file_path=None,
                    line_start=None,
                    line_end=None,
                    content_hash=None,
                )
                new = self._create_core(db, identity_id, old.type, normalized, supersedes_id=old.id)
                db.commit()
            except Exception:
                db.rollback()
                raise
            return _summary(db, new)

    def complete(self, memory_id: str) -> MemorySummary:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            memory = self.memories.get_owned(db, identity_id, memory_id)
            if memory is None:
                raise ValueError("记忆不存在")
            if memory.status != "active" or memory.type not in ("goal", "project"):
                raise ValueError("只能完成有效的目标或项目")
            self.jobs.cancel_pending(db, identity_id)
            self.memories.update(db, memory, status="completed")
            db.commit()
            return _summary(db, memory)

    def forget(self, memory_id: str) -> None:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            memory = self.memories.get_owned(db, identity_id, memory_id)
            if memory is None:
                raise ValueError("记忆不存在")
            self.jobs.cancel_pending(db, identity_id)
            self._remove_from_file(memory)
            self.memories.delete_owned(db, identity_id, memory.id)
            db.commit()

    def forget_conversation(self, conversation_id: str) -> int:
        """删除某会话派生的情景观察，并记录遗忘墓碑。返回删除条数。"""
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self.jobs.cancel_pending(db, identity_id)
            episodic = [
                item
                for item in self.memories.list_owned(
                    db, identity_id, tier="episodic", statuses=None
                )
                if item.conversation_id == conversation_id
            ]
            for memory in episodic:
                self._remove_from_file(memory)
                self.memories.delete_owned(db, identity_id, memory.id)
            db.add(
                ForgottenConversation(
                    id=str(uuid4()), conversation_id=conversation_id
                )
            )
            db.commit()
            return len(episodic)

    def _create_core(
        self,
        db,
        identity_id: str,
        memory_type: str,
        content: str,
        *,
        supersedes_id: str | None = None,
    ) -> Memory:
        path = self.store.path_for(memory_type)
        entry = self.store.append(path, content, meta={"type": memory_type})
        memory = self.memories.create(
            db,
            type=memory_type,
            content=entry.content,
            identity_id=identity_id,
            origin="manual",
            tier="core",
            trust="owner",
            source_kind="manual",
            supersedes_id=supersedes_id,
            file_path=path.name,
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
        )
        embed_and_store(db, memory.id, memory.content)
        return memory

    def _remove_from_file(self, memory: Memory) -> None:
        if not memory.file_path or not memory.content_hash:
            return
        path = self.store.dir / memory.file_path
        index = self.store.index_by_hash(path, memory.content_hash)
        if index is not None:
            self.store.remove(path, index)

    @staticmethod
    def _validate(type: str, content: str) -> tuple[str, str]:
        memory_type = type.strip().lower()
        normalized = content.strip()
        if memory_type not in MEMORY_TYPES:
            raise ValueError("无效的记忆类型")
        if not normalized:
            raise ValueError("记忆内容不能为空")
        if len(normalized) > 500:
            raise ValueError("记忆内容不能超过 500 字符")
        return memory_type, normalized
