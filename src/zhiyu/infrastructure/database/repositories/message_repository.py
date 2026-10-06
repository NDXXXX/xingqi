"""Message 仓储。"""

from uuid import uuid4

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from ..models import Message


class MessageRepository:
    def list_by_conversation(self, db: Session, conversation_id: str) -> list[Message]:
        return list(
            db.scalars(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at, Message.id)
            )
        )

    def list_after(
        self,
        db: Session,
        conversation_id: str,
        created_at,
        message_id: str,
    ) -> list[Message]:
        return list(
            db.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    or_(
                        Message.created_at > created_at,
                        and_(Message.created_at == created_at, Message.id > message_id),
                    ),
                )
                .order_by(Message.created_at, Message.id)
            )
        )

    def create(
        self,
        db: Session,
        *,
        conversation_id: str,
        role: str,
        content: str,
        parts_json: str | None = None,
        source_event_id: str | None = None,
        commit: bool = True,
    ) -> Message:
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            role=role,
            content=content,
            parts_json=parts_json,
            source_event_id=source_event_id,
        )
        db.add(message)
        if commit:
            db.commit()
            db.refresh(message)
        else:
            db.flush()
        return message

    def get_by_source(
        self, db: Session, source_event_id: str, role: str
    ) -> Message | None:
        return db.scalars(
            select(Message)
            .where(
                Message.source_event_id == source_event_id,
                Message.role == role,
            )
            .order_by(Message.created_at)
        ).first()

    def prepare_regeneration(self, db: Session, conversation_id: str) -> Message | None:
        messages = self.list_by_conversation(db, conversation_id)
        user_message = next((message for message in reversed(messages) if message.role == "user"), None)
        if user_message is None:
            return None
        user_index = messages.index(user_message)
        later_ids = [message.id for message in messages[user_index + 1 :]]
        if later_ids:
            db.execute(delete(Message).where(Message.id.in_(later_ids)))
            from ..models import ConversationSummary

            db.query(ConversationSummary).filter(
                ConversationSummary.conversation_id == conversation_id,
                ConversationSummary.last_message_id.in_(later_ids),
            ).delete(synchronize_session=False)
            db.commit()
        return user_message
