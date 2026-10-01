"""Message 仓储。"""

from uuid import uuid4

from sqlalchemy import delete, select
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

    def create(
        self,
        db: Session,
        *,
        conversation_id: str,
        role: str,
        content: str,
        commit: bool = True,
    ) -> Message:
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
        )
        db.add(message)
        if commit:
            db.commit()
            db.refresh(message)
        else:
            db.flush()
        return message

    def prepare_regeneration(self, db: Session, conversation_id: str) -> Message | None:
        messages = self.list_by_conversation(db, conversation_id)
        user_message = next((message for message in reversed(messages) if message.role == "user"), None)
        if user_message is None:
            return None
        user_index = messages.index(user_message)
        later_ids = [message.id for message in messages[user_index + 1 :]]
        if later_ids:
            db.execute(delete(Message).where(Message.id.in_(later_ids)))
            db.commit()
        return user_message
