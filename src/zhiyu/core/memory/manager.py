"""Memory 管理：提取情景观察并以单个事务写入文件 + 索引。"""

import re
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import (
    ForgottenConversation,
    Memory,
    MemorySource,
    Message,
    utcnow,
)
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.providers.base import AIProvider
from zhiyu.core.providers.embedding import embed_and_store
from .extractor import extract_observations
from .mutations import FileMutationManager
from .retriever import _lexical_similarity, derive_trigger_text
from .safety import contains_secret
from .store import MemoryStore


class MemoryManager:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.repo = MemoryRepository()
        self.store = store or MemoryStore()
        self.mutations = FileMutationManager(self.store)

    async def extract_and_save(
        self,
        db: Session,
        provider: AIProvider,
        model: str,
        user_msg: str,
        assistant_msg: str,
        identity_id: str,
        *,
        user_message_id: str | None = None,
        history: list[dict] | None = None,
        should_apply: Callable[[], bool] | None = None,
        commit: bool = True,
    ) -> list[Memory]:
        if not identity_id:
            raise ValueError("保存记忆必须指定身份")

        observations = await extract_observations(
            provider,
            model,
            user_message=user_msg,
            assistant_message=assistant_msg,
            history=history or [],
        )
        if not observations:
            return []
        if should_apply is not None and not should_apply():
            return []

        conversation_id = self._conversation_of(db, user_message_id) if user_message_id else None
        if conversation_id and db.scalars(
            select(ForgottenConversation.id).where(
                ForgottenConversation.identity_id == identity_id,
                ForgottenConversation.conversation_id == conversation_id,
            )
        ).first() is not None:
            return []

        changed: list[Memory] = []
        seen: set[tuple[str, str]] = set()
        explicit_request = bool(re.search(r"记住|记下来|帮我记", user_msg))
        try:
            for observation in observations:
                if observation["evidence"] not in user_msg:
                    continue
                if contains_secret(observation["content"]):
                    continue
                key = (observation["type"], observation["content"].strip())
                if key in seen:
                    continue
                seen.add(key)
                if explicit_request:
                    changed.append(
                        self._write_explicit_core(
                            db,
                            identity_id,
                            observation,
                            user_message_id,
                            conversation_id,
                        )
                    )
                    continue
                corrected = self._apply_explicit_correction(
                    db,
                    identity_id,
                    observation,
                    user_msg,
                    user_message_id,
                    conversation_id,
                )
                if corrected is None:
                    written = self._write_episodic(
                        db,
                        identity_id,
                        observation,
                        user_message_id,
                        conversation_id,
                    )
                    self._reopen_related_candidates(
                        db, identity_id, written, observation
                    )
                    self._refresh_active_work(
                        db,
                        identity_id,
                        observation,
                        user_message_id,
                        conversation_id,
                    )
                    changed.append(written)
                else:
                    changed.append(corrected)
            if commit:
                db.commit()
            else:
                db.flush()
        except Exception:
            db.rollback()
            raise
        return changed

    def _write_explicit_core(
        self,
        db: Session,
        identity_id: str,
        observation: dict,
        user_message_id: str | None,
        conversation_id: str | None,
    ) -> Memory:
        candidates = [
            item
            for item in self.repo.list_owned(db, identity_id, tier="core")
            if item.status == "active"
            and item.type == observation["type"]
            and _lexical_similarity(item.content, observation["content"]) >= 0.28
        ]
        if len(candidates) == 1:
            old = candidates[0]
            if _lexical_similarity(old.content, observation["content"]) >= 0.75:
                self._add_confirmation_source(
                    db, identity_id, old, user_message_id, conversation_id
                )
                old.last_evidence_at = utcnow()
                return old
            path = self.store.resolve_relative(old.file_path) if old.file_path else self.store.path_for(old.type, identity_id)
            entry, mutation = self.mutations.replace(
                db,
                identity_id,
                path,
                old.entry_key,
                observation["content"],
                meta={"type": observation["type"]},
                context={
                    "origin": "automatic",
                    "tier": "core",
                    "trust": "owner",
                    "source_kind": "message",
                    "source_message_id": user_message_id,
                    "conversation_id": conversation_id,
                    "supersedes_id": old.id,
                },
            )
            replacement = self.repo.create(
                db,
                type=observation["type"],
                content=entry.content,
                identity_id=identity_id,
                origin="automatic",
                tier="core",
                trust="owner",
                source_kind="message",
                trigger_text=derive_trigger_text(entry.content),
                source_message_id=user_message_id,
                conversation_id=conversation_id,
                supersedes_id=old.id,
                file_path=self.store.relative_path(path),
                line_start=entry.line_start,
                line_end=entry.line_end,
                content_hash=entry.hash,
                entry_key=entry.id,
            )
            self.repo.update(
                db,
                old,
                status="superseded",
                status_source_message_id=user_message_id,
                file_path=None,
                line_start=None,
                line_end=None,
                content_hash=None,
            )
            db.add(
                MemorySource(
                    id=str(uuid4()),
                    memory_id=replacement.id,
                    identity_id=identity_id,
                    source_memory_id=old.id,
                    source_message_id=user_message_id,
                    conversation_id=conversation_id,
                    trust="owner",
                    source_kind="correction",
                )
            )
            self.mutations.complete(db, mutation)
            embed_and_store(db, replacement.id, replacement.content)
            return replacement

        path = self.store.path_for(observation["type"], identity_id)
        entry, mutation = self.mutations.append(
            db,
            identity_id,
            path,
            observation["content"],
            meta={"type": observation["type"]},
            context={
                "origin": "automatic",
                "tier": "core",
                "trust": "owner",
                "source_kind": "message",
                "source_message_id": user_message_id,
                "conversation_id": conversation_id,
            },
        )
        memory = self.repo.create(
            db,
            type=observation["type"],
            content=entry.content,
            identity_id=identity_id,
            origin="automatic",
            tier="core",
            trust="owner",
            source_kind="message",
            source_message_id=user_message_id,
            conversation_id=conversation_id,
            trigger_text=derive_trigger_text(entry.content),
            file_path=self.store.relative_path(path),
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        embed_and_store(db, memory.id, memory.content)
        self.mutations.complete(db, mutation)
        return memory

    def _reopen_related_candidates(self, db, identity_id, written, observation) -> None:
        """新独立证据到达时，把旧暂缓或旧版 rejected 观察重新纳入沉淀。"""
        for item in self.repo.list_owned(db, identity_id, tier="episodic"):
            if (
                item.id != written.id
                and item.status == "active"
                and item.type == observation["type"]
                and item.promotion_status in {"deferred", "rejected"}
                and self._independent(item, written)
                and _lexical_similarity(item.content, written.content) >= 0.18
            ):
                item.promotion_status = "pending"
                item.updated_at = utcnow()

    @staticmethod
    def _independent(left: Memory, right: Memory) -> bool:
        if left.source_message_id and right.source_message_id:
            return left.source_message_id != right.source_message_id
        return (left.observed_at or left.created_at).date() != (
            right.observed_at or right.created_at
        ).date()

    def _refresh_active_work(
        self, db, identity_id, observation, user_message_id, conversation_id
    ) -> None:
        if observation["type"] not in {"goal", "project"} or not user_message_id:
            return
        matches = [
            item
            for item in self.repo.list_owned(db, identity_id, tier="core")
            if item.type == observation["type"]
            and item.status == "active"
            and _lexical_similarity(item.content, observation["content"]) >= 0.18
        ]
        if len(matches) == 1:
            self._add_confirmation_source(
                db, identity_id, matches[0], user_message_id, conversation_id
            )
            matches[0].last_evidence_at = utcnow()

    @staticmethod
    def _add_confirmation_source(
        db, identity_id, memory, user_message_id, conversation_id
    ) -> None:
        if not user_message_id:
            return
        exists = db.scalars(
            select(MemorySource.id).where(
                MemorySource.identity_id == identity_id,
                MemorySource.memory_id == memory.id,
                MemorySource.source_message_id == user_message_id,
            )
        ).first()
        if exists is None:
            db.add(
                MemorySource(
                    id=str(uuid4()),
                    memory_id=memory.id,
                    identity_id=identity_id,
                    source_message_id=user_message_id,
                    conversation_id=conversation_id,
                    trust="owner",
                    source_kind="confirmation",
                    observed_at=utcnow(),
                )
            )

    def _write_episodic(
        self,
        db: Session,
        identity_id: str,
        observation: dict,
        user_message_id: str | None,
        conversation_id: str | None,
    ) -> Memory:
        path = self.store.daily_path(identity_id=identity_id)
        entry, mutation = self.mutations.append(
            db,
            identity_id,
            path,
            observation["content"],
            meta={"type": observation["type"]},
            context={
                "origin": "automatic",
                "tier": "episodic",
                "trust": "agent",
                "source_kind": "message",
                "promotion_status": "pending",
                "source_message_id": user_message_id,
                "conversation_id": conversation_id,
            },
        )
        memory = self.repo.create(
            db,
            type=observation["type"],
            content=entry.content,
            identity_id=identity_id,
            source_message_id=user_message_id,
            tier="episodic",
            trust="agent",
            source_kind="message",
            promotion_status="pending",
            conversation_id=conversation_id,
            file_path=self.store.relative_path(path),
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        embed_and_store(db, memory.id, memory.content)
        self.mutations.complete(db, mutation)
        return memory

    def _apply_explicit_correction(
        self,
        db: Session,
        identity_id: str,
        observation: dict,
        user_message: str,
        user_message_id: str | None,
        conversation_id: str | None,
    ) -> Memory | None:
        """明确改口且只对应一个核心条目时立即替换；含糊时仍走 episodic。"""
        if observation["type"] not in {"profile", "preference", "fact", "relationship"}:
            return None
        if not re.search(r"不再|不要|别再|改成|改为|已经不是|不喝|不吃|戒了|搬到|现在住", user_message):
            return None
        candidates = [
            memory
            for memory in self.repo.list_owned(db, identity_id, tier="core")
            if memory.type == observation["type"]
            and memory.file_path
            and memory.entry_key
            and _lexical_similarity(memory.content, observation["content"]) >= 0.28
        ]
        if len(candidates) != 1:
            return None

        old = candidates[0]
        path = self.store.resolve_relative(old.file_path)
        entry, mutation = self.mutations.replace(
            db,
            identity_id,
            path,
            old.entry_key,
            observation["content"],
            meta={"type": observation["type"]},
            context={
                "origin": "automatic",
                "tier": "core",
                "trust": "owner",
                "source_kind": "message",
                "promotion_status": "none",
                "source_message_id": user_message_id,
                "conversation_id": conversation_id,
                "supersedes_id": old.id,
            },
        )
        replacement = self.repo.create(
            db,
            type=observation["type"],
            content=entry.content,
            identity_id=identity_id,
            source_message_id=user_message_id,
            supersedes_id=old.id,
            origin="automatic",
            tier="core",
            trust="owner",
            source_kind="message",
            trigger_text=derive_trigger_text(entry.content),
            conversation_id=conversation_id,
            file_path=self.store.relative_path(path),
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        self.repo.update(
            db,
            old,
            status="superseded",
            status_source_message_id=user_message_id,
            file_path=None,
            line_start=None,
            line_end=None,
            content_hash=None,
            updated_at=utcnow(),
        )
        db.add(
            MemorySource(
                id=str(uuid4()),
                memory_id=replacement.id,
                identity_id=identity_id,
                source_message_id=user_message_id,
                conversation_id=conversation_id,
                trust="owner",
                source_kind="message",
            )
        )
        embed_and_store(db, replacement.id, replacement.content)
        self.mutations.complete(db, mutation)
        return replacement

    @staticmethod
    def _conversation_of(db: Session, message_id: str) -> str | None:
        message = db.get(Message, message_id)
        return message.conversation_id if message is not None else None
