"""Message 仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Message


class MessageRepository:
    def list_by_conversation(self, db: Session, conversation_id: str) -> list[Message]:
        return list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        )

    def create(self, db: Session, *, conversation_id: str, role: str, content: str) -> Message:
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
