"""Memory 仓储：所有产品读取都显式限定身份。"""

from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Memory, utcnow


class MemoryRepository:
    def list_visible(
        self,
        db: Session,
        identity_id: str,
        *,
        include_shared: bool = True,
        statuses: tuple[str, ...] | None = ("active",),
        tier: str | None = None,
    ) -> list[Memory]:
        if not identity_id:
            raise ValueError("读取记忆必须指定身份")
        condition = Memory.identity_id == identity_id
        if include_shared:
            condition = or_(condition, Memory.shared.is_(True))
        query = select(Memory).where(condition)
        if statuses is not None:
            query = query.where(Memory.status.in_(statuses))
        if tier is not None:
            query = query.where(Memory.tier == tier)
        return list(db.scalars(query.order_by(Memory.updated_at.desc(), Memory.created_at.desc())))

    def list_owned(
        self,
        db: Session,
        identity_id: str,
        *,
        statuses: tuple[str, ...] | None = ("active",),
        tier: str | None = None,
    ) -> list[Memory]:
        return self.list_visible(db, identity_id, include_shared=False, statuses=statuses, tier=tier)

    def list(
        self,
        db: Session,
        identity_id: str,
        *,
        include_shared: bool = True,
    ) -> list[Memory]:
        """兼容旧调用；默认只返回可见且有效的记忆。"""
        return self.list_visible(db, identity_id, include_shared=include_shared)

    def get(self, db: Session, memory_id: str) -> Memory | None:
        return db.get(Memory, memory_id)

    def get_owned(self, db: Session, identity_id: str, memory_id: str) -> Memory | None:
        if not identity_id:
            raise ValueError("读取记忆必须指定身份")
        return db.scalars(
            select(Memory).where(Memory.id == memory_id, Memory.identity_id == identity_id)
        ).first()

    def has_source_action(self, db: Session, identity_id: str, message_id: str) -> bool:
        return db.scalars(
            select(Memory.id).where(
                Memory.identity_id == identity_id,
                or_(
                    Memory.source_message_id == message_id,
                    Memory.status_source_message_id == message_id,
                ),
            )
        ).first() is not None

    def create(
        self,
        db: Session,
        *,
        type: str,
        content: str,
        identity_id: str,
        user_id: str | None = None,
        shared: bool = False,
        importance: float = 0.5,
        status: str = "active",
        source_message_id: str | None = None,
        status_source_message_id: str | None = None,
        supersedes_id: str | None = None,
        origin: str = "automatic",
        tier: str = "core",
        trust: str = "agent",
        source_kind: str = "message",
        supersession_key: str | None = None,
        trigger_text: str | None = None,
        promotion_status: str = "none",
        promoted_to_id: str | None = None,
        conversation_id: str | None = None,
        file_path: str | None = None,
        line_start: int | None = None,
        line_end: int | None = None,
        content_hash: str | None = None,
        entry_key: str | None = None,
    ) -> Memory:
        if not identity_id:
            raise ValueError("保存记忆必须指定身份")
        memory = Memory(
            id=str(uuid4()),
            user_id=user_id,
            identity_id=identity_id,
            shared=shared,
            type=type,
            content=content,
            importance=importance,
            status=status,
            source_message_id=source_message_id,
            status_source_message_id=status_source_message_id,
            supersedes_id=supersedes_id,
            origin=origin,
            tier=tier,
            trust=trust,
            source_kind=source_kind,
            supersession_key=supersession_key,
            trigger_text=trigger_text,
            promotion_status=promotion_status,
            promoted_to_id=promoted_to_id,
            conversation_id=conversation_id,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            content_hash=content_hash,
            entry_key=entry_key,
        )
        db.add(memory)
        db.flush()
        return memory

    def update(self, db: Session, memory: Memory, **fields) -> Memory:
        for key, value in fields.items():
            if hasattr(memory, key):
                setattr(memory, key, value)
        memory.updated_at = utcnow()
        db.flush()
        return memory

    def delete(self, db: Session, memory_id: str) -> bool:
        memory = self.get(db, memory_id)
        if memory is None:
            return False
        db.delete(memory)
        db.flush()
        return True

    def delete_owned(self, db: Session, identity_id: str, memory_id: str) -> bool:
        memory = self.get_owned(db, identity_id, memory_id)
        if memory is None:
            return False
        db.delete(memory)
        db.flush()
        return True
