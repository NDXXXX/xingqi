"""Memory 仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Memory, utcnow


class MemoryRepository:
    def list(self, db: Session) -> list[Memory]:
        return list(db.scalars(select(Memory).order_by(Memory.created_at.desc())))

    def get(self, db: Session, memory_id: str) -> Memory | None:
        return db.get(Memory, memory_id)

    def create(
        self,
        db: Session,
        *,
        type: str,
        content: str,
        user_id: str | None = None,
        importance: float = 0.5,
    ) -> Memory:
        memory = Memory(
            id=str(uuid4()),
            user_id=user_id,
            type=type,
            content=content,
            importance=importance,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory

    def update(self, db: Session, memory: Memory, **fields) -> Memory:
        for key, value in fields.items():
            if hasattr(memory, key):
                setattr(memory, key, value)
        memory.updated_at = utcnow()
        db.commit()
        db.refresh(memory)
        return memory

    def delete(self, db: Session, memory_id: str) -> bool:
        memory = self.get(db, memory_id)
        if memory is None:
            return False
        db.delete(memory)
        db.commit()
        return True
