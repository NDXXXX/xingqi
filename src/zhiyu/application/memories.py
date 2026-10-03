"""本地用户的记忆查看、纠正和删除用例。手动记忆直接写入长期核心（文件 + 索引）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select

from zhiyu.core.memory.extractor import MEMORY_TYPES
from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.core.memory.mutations import FileMutationManager
from zhiyu.core.memory.retriever import derive_trigger_text, hybrid_rank
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.embedding import embed_and_store
from zhiyu.core.providers.embedding import load_config as load_embedding_config
from zhiyu.core.providers.embedding import resolve_api_key
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import (
    Conversation,
    ForgottenConversation,
    Memory,
    MemoryMutation,
    MemoryRecallEvent,
    MemorySource,
    Message,
    utcnow,
)
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
        self.mutations = FileMutationManager(self.store)

    def list(self, *, include_inactive: bool = False, tier: str | None = None) -> list[MemorySummary]:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
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
            self._sync(db, identity_id)
            memory = self.memories.get_owned(db, identity_id, memory_id)
            return _summary(db, memory) if memory is not None else None

    def recall_explain(self, query: str) -> dict:
        if not query.strip():
            raise ValueError("查询不能为空")
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            memories = [
                *self.memories.list_visible(db, identity_id, tier="core"),
                *self.memories.list_owned(db, identity_id, tier="episodic"),
            ]
            trace = hybrid_rank(db, query, memories)
            return {
                "query_plan": {
                    "normalized": trace.plan.normalized,
                    "variants": trace.plan.variants,
                    "temporal_intent": trace.plan.temporal_intent,
                    "recall_intent": trace.plan.recall_intent,
                },
                "candidates": [
                    {
                        "id": item.memory.id,
                        "type": item.memory.type,
                        "tier": item.memory.tier,
                        "channels": item.channels,
                        "rrf_score": item.rrf_score,
                        "confidence": item.confidence,
                        "filtered_reason": item.filtered_reason,
                    }
                    for item in trace.candidates
                ],
                "selected_ids": [item.memory.id for item in trace.selected],
            }

    def status(self) -> dict[str, int | str]:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            result: dict[str, int | str] = {
                f"jobs_{key}": value for key, value in self.jobs.counts(db).items()
            }
            mutation_counts = db.execute(
                select(MemoryMutation.status, func.count(MemoryMutation.id))
                .where(MemoryMutation.identity_id == identity_id)
                .group_by(MemoryMutation.status)
            ).all()
            for status, count in mutation_counts:
                result[f"mutations_{status}"] = count
            for status in ("prepared", "file_applied", "failed"):
                result.setdefault(f"mutations_{status}", 0)
            last_recall = db.scalars(
                select(MemoryRecallEvent).order_by(
                    MemoryRecallEvent.created_at.desc()
                ).where(MemoryRecallEvent.identity_id == identity_id)
            ).first()
            if last_recall is not None:
                result["last_recall_mode"] = last_recall.recall_mode
                result["last_recall_injected_count"] = db.scalar(
                    select(func.count(MemoryRecallEvent.id)).where(
                        MemoryRecallEvent.identity_id == last_recall.identity_id,
                        MemoryRecallEvent.query_hash == last_recall.query_hash,
                        MemoryRecallEvent.created_at
                        >= last_recall.created_at - timedelta(seconds=2),
                    )
                ) or 0
            config = load_embedding_config(db)
            if config is None:
                result["embedding"] = "lexical_only:not_configured"
            elif not resolve_api_key(config.api_key_ref):
                result["embedding"] = "lexical_only:missing_credentials"
            else:
                result["embedding"] = f"configured:{config.model}"
            return result

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
            self._sync(db, identity_id)
            old = self.memories.get_owned(db, identity_id, memory_id)
            if old is None:
                raise ValueError("记忆不存在")
            if old.status != "active":
                raise ValueError("只能修改有效记忆")
            _, normalized = self._validate(old.type, content)
            self.jobs.cancel_pending(db, identity_id)
            try:
                mutation = None
                if old.file_path and old.entry_key:
                    path = self.store.resolve_relative(old.file_path)
                    entry, mutation = self.mutations.replace(
                        db,
                        identity_id,
                        path,
                        old.entry_key,
                        normalized,
                        meta={"type": old.type},
                        context={
                            "origin": "manual",
                            "tier": "core",
                            "trust": "owner",
                            "source_kind": "manual",
                            "promotion_status": "none",
                            "supersedes_id": old.id,
                        },
                    )
                    new = self._create_core_record(
                        db,
                        identity_id,
                        old.type,
                        entry,
                        path,
                        supersedes_id=old.id,
                    )
                else:
                    self._remove_from_file(db, identity_id, old)
                    new = self._create_core(
                        db, identity_id, old.type, normalized, supersedes_id=old.id
                    )
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
                if mutation is not None:
                    self.mutations.complete(db, mutation)
                db.commit()
            except Exception:
                db.rollback()
                raise
            return _summary(db, new)

    def complete(self, memory_id: str) -> MemorySummary:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            memory = self.memories.get_owned(db, identity_id, memory_id)
            if memory is None:
                raise ValueError("记忆不存在")
            if memory.status != "active" or memory.type not in ("goal", "project"):
                raise ValueError("只能完成有效的目标或项目")
            self.jobs.cancel_pending(db, identity_id)
            mutation = self._remove_from_file(
                db, identity_id, memory, context={"lifecycle": "completed"}
            )
            self.memories.update(db, memory, status="completed")
            if mutation is not None:
                self.mutations.complete(db, mutation)
            db.commit()
            return _summary(db, memory)

    def forget(self, memory_id: str) -> None:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            memory = self.memories.get_owned(db, identity_id, memory_id)
            if memory is None:
                raise ValueError("记忆不存在")
            self.jobs.cancel_pending(db, identity_id)
            source_rows = list(
                db.scalars(
                    select(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        MemorySource.source_memory_id == memory.id,
                    )
                )
            )
            orphaned_cores = self._orphaned_cores_after_removal(
                db, identity_id, source_rows
            )
            cascade_core_ids = [core.id for core in orphaned_cores]
            mutations = []
            for target in [memory, *orphaned_cores]:
                mutation = self._remove_from_file(
                    db,
                    identity_id,
                    target,
                    context={
                        "lifecycle": "delete",
                        "cascade_core_ids": cascade_core_ids,
                    },
                )
                if mutation is not None:
                    mutations.append(mutation)
            for source in source_rows:
                db.delete(source)
            self.memories.delete_owned(db, identity_id, memory.id)
            for core in orphaned_cores:
                self.memories.delete_owned(db, identity_id, core.id)
            for mutation in mutations:
                self.mutations.complete(db, mutation)
            db.commit()

    def plan_forget(
        self,
        *,
        memory_id: str | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        """只读枚举遗忘影响；CLI 默认先展示该计划。"""
        if bool(memory_id) == bool(conversation_id):
            raise ValueError("必须且只能指定记忆或会话")
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            if memory_id:
                memory = self.memories.get_owned(db, identity_id, memory_id)
                if memory is None:
                    raise ValueError("记忆不存在")
                source_rows = list(
                    db.scalars(
                        select(MemorySource).where(
                            MemorySource.identity_id == identity_id,
                            MemorySource.source_memory_id == memory.id,
                        )
                    )
                )
                orphaned_cores = self._orphaned_cores_after_removal(
                    db, identity_id, source_rows
                )
                return {
                    "kind": "memory",
                    "identity_id": identity_id,
                    "entries": [
                        {
                            "id": memory.id,
                            "tier": memory.tier,
                            "content": memory.content,
                            "file_path": memory.file_path,
                            "action": "delete",
                        }
                    ]
                    + [
                        {
                            "id": core.id,
                            "tier": core.tier,
                            "content": core.content,
                            "file_path": core.file_path,
                            "action": "delete",
                        }
                        for core in orphaned_cores
                    ],
                }

            conversation = db.get(Conversation, conversation_id)
            if conversation is None or conversation.identity_id != identity_id:
                raise ValueError("会话不存在或不属于当前身份")
            episodic = [
                item
                for item in self.memories.list_owned(
                    db, identity_id, tier="episodic", statuses=None
                )
                if item.conversation_id == conversation_id
            ]
            source_rows = list(
                db.scalars(
                    select(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        MemorySource.conversation_id == conversation_id,
                    )
                )
            )
            core_ids = {item.promoted_to_id for item in episodic if item.promoted_to_id}
            core_ids.update(row.memory_id for row in source_rows)
            entries = [
                {
                    "id": item.id,
                    "tier": item.tier,
                    "content": item.content,
                    "file_path": item.file_path,
                    "action": "delete",
                }
                for item in episodic
            ]
            for core_id in sorted(core_ids):
                core = self.memories.get_owned(db, identity_id, core_id)
                if core is None:
                    continue
                remaining_source = any(
                    source_conversation_id != conversation_id
                    for source_conversation_id in db.scalars(
                        select(MemorySource.conversation_id).where(
                            MemorySource.identity_id == identity_id,
                            MemorySource.memory_id == core_id,
                        )
                    )
                )
                legacy_remaining = any(
                    item.promoted_to_id == core_id
                    and item.conversation_id != conversation_id
                    for item in self.memories.list_owned(
                        db, identity_id, tier="episodic", statuses=None
                    )
                )
                delete = (
                    core.origin == "automatic"
                    and not remaining_source
                    and not legacy_remaining
                )
                entries.append(
                    {
                        "id": core.id,
                        "tier": core.tier,
                        "content": core.content,
                        "file_path": core.file_path,
                        "action": "delete" if delete else "retain",
                    }
                )
            return {
                "kind": "conversation",
                "identity_id": identity_id,
                "conversation_id": conversation_id,
                "entries": entries,
                "tombstone": True,
            }

    def forget_conversation(self, conversation_id: str) -> int:
        """删除某会话派生的情景观察，并记录遗忘墓碑。返回删除条数。"""
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            conversation = db.get(Conversation, conversation_id)
            if conversation is None or conversation.identity_id != identity_id:
                raise ValueError("会话不存在或不属于当前身份")
            self.jobs.cancel_pending(db, identity_id)
            episodic = [
                item
                for item in self.memories.list_owned(
                    db, identity_id, tier="episodic", statuses=None
                )
                if item.conversation_id == conversation_id
            ]
            promoted_ids = {item.promoted_to_id for item in episodic if item.promoted_to_id}
            source_rows = list(
                db.scalars(
                    select(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        MemorySource.conversation_id == conversation_id,
                    )
                )
            )
            promoted_ids.update(row.memory_id for row in source_rows)
            cores_to_delete = []
            for core_id in promoted_ids:
                remaining_source = any(
                    source_conversation_id != conversation_id
                    for source_conversation_id in db.scalars(
                        select(MemorySource.conversation_id).where(
                            MemorySource.identity_id == identity_id,
                            MemorySource.memory_id == core_id,
                        )
                    )
                )
                legacy_remaining = any(
                    item.promoted_to_id == core_id
                    and item.conversation_id != conversation_id
                    for item in self.memories.list_owned(
                        db, identity_id, tier="episodic", statuses=None
                    )
                )
                if remaining_source or legacy_remaining:
                    continue
                core = self.memories.get_owned(db, identity_id, core_id)
                if core is not None and core.origin == "automatic":
                    cores_to_delete.append(core)

            # 先完成全部可恢复文件操作，再改变来源图和业务行；mutation
            # 的 prepare 提交不会意外提交半套遗忘结果。
            mutations = []
            cascade_core_ids = [core.id for core in cores_to_delete]
            for memory in [*episodic, *cores_to_delete]:
                mutation = self._remove_from_file(
                    db,
                    identity_id,
                    memory,
                    context={
                        "lifecycle": "delete",
                        "forgotten_conversation_id": conversation_id,
                        "cascade_core_ids": cascade_core_ids,
                    },
                )
                if mutation is not None:
                    mutations.append(mutation)

            for source in source_rows:
                db.delete(source)
            db.flush()
            for memory in episodic:
                self.memories.delete_owned(db, identity_id, memory.id)
            for core in cores_to_delete:
                self.memories.delete_owned(db, identity_id, core.id)
            exists = db.query(ForgottenConversation).filter_by(
                identity_id=identity_id, conversation_id=conversation_id
            ).first()
            if exists is None:
                db.add(
                    ForgottenConversation(
                        id=str(uuid4()),
                        identity_id=identity_id,
                        conversation_id=conversation_id,
                    )
                )
            for mutation in mutations:
                self.mutations.complete(db, mutation)
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
        path = self.store.path_for(memory_type, identity_id)
        entry, mutation = self.mutations.append(
            db,
            identity_id,
            path,
            content,
            meta={"type": memory_type},
            context={
                "origin": "manual",
                "tier": "core",
                "trust": "owner",
                "source_kind": "manual",
                "promotion_status": "none",
                "supersedes_id": supersedes_id,
            },
        )
        memory = self._create_core_record(
            db,
            identity_id,
            memory_type,
            entry,
            path,
            supersedes_id=supersedes_id,
        )
        self.mutations.complete(db, mutation)
        return memory

    def _create_core_record(
        self,
        db,
        identity_id: str,
        memory_type: str,
        entry,
        path,
        *,
        supersedes_id: str | None = None,
    ) -> Memory:
        memory = self.memories.create(
            db,
            type=memory_type,
            content=entry.content,
            identity_id=identity_id,
            origin="manual",
            tier="core",
            trust="owner",
            source_kind="manual",
            trigger_text=derive_trigger_text(entry.content),
            supersedes_id=supersedes_id,
            file_path=self.store.relative_path(path),
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        embed_and_store(db, memory.id, memory.content)
        return memory

    def _remove_from_file(
        self,
        db,
        identity_id: str,
        memory: Memory,
        *,
        context: dict | None = None,
    ):
        if not memory.file_path or not memory.content_hash:
            return None
        path = self.store.resolve_relative(memory.file_path)
        if memory.entry_key:
            return self.mutations.remove(
                db,
                identity_id,
                path,
                memory.entry_key,
                context=context,
            )
        index = self.store.index_by_hash(path, memory.content_hash)
        if index is not None:
            self.store.remove(path, index)
        return None

    def _sync(self, db, identity_id: str) -> None:
        rebuild_index(db, self.store, identity_id)

    def _orphaned_cores_after_removal(
        self, db, identity_id: str, removing: list[MemorySource]
    ) -> list[Memory]:
        removing_ids = {source.id for source in removing}
        core_ids = {source.memory_id for source in removing}
        orphaned = []
        for core_id in core_ids:
            remaining = any(
                source.id not in removing_ids
                for source in db.scalars(
                    select(MemorySource).where(
                        MemorySource.identity_id == identity_id,
                        MemorySource.memory_id == core_id,
                    )
                )
            )
            core = self.memories.get_owned(db, identity_id, core_id)
            if not remaining and core is not None and core.origin == "automatic":
                orphaned.append(core)
        return orphaned

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
