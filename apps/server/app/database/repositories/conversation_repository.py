"""Conversation 仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Conversation, utcnow


class ConversationRepository:
    def list(self, db: Session, query: str | None = None) -> list[Conversation]:
        statement = select(Conversation)
        if query:
            statement = statement.where(Conversation.title.contains(query.strip()))
        return list(db.scalars(statement.order_by(Conversation.updated_at.desc())))

    def get(self, db: Session, conversation_id: str) -> Conversation | None:
        return db.get(Conversation, conversation_id)

    def get_by_external(
        self, db: Session, channel: str, external_user_id: str
    ) -> Conversation | None:
        return db.scalars(
            select(Conversation)
            .where(Conversation.channel == channel, Conversation.external_user_id == external_user_id)
            .order_by(Conversation.updated_at.desc())
        ).first()

    def create(
        self,
        db: Session,
        *,
        title: str,
        channel: str,
        character_id: str | None = None,
        external_user_id: str | None = None,
        model_id: str | None = None,
        identity_id: str | None = None,
    ) -> Conversation:
        conversation = Conversation(
            id=str(uuid4()),
            title=title,
            channel=channel,
            character_id=character_id,
            external_user_id=external_user_id,
            model_id=model_id,
            identity_id=identity_id,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def delete(self, db: Session, conversation_id: str) -> bool:
        conversation = self.get(db, conversation_id)
        if conversation is None:
            return False
        db.delete(conversation)
        db.commit()
        return True

    def touch(self, db: Session, conversation_id: str, model_id: str | None = None) -> None:
        conversation = self.get(db, conversation_id)
        if conversation is None:
            return
        if model_id is not None:
            conversation.model_id = model_id
        conversation.updated_at = utcnow()
        db.commit()
