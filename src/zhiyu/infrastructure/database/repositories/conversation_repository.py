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
        self,
        db: Session,
        channel: str,
        external_user_id: str,
        *,
        channel_config_id: str | None = None,
        conversation_type: str | None = None,
    ) -> Conversation | None:
        statement = select(Conversation).where(
            Conversation.channel == channel,
            Conversation.external_user_id == external_user_id,
        )
        if channel_config_id is not None:
            statement = statement.where(
                (Conversation.channel_config_id == channel_config_id)
                | (Conversation.channel_config_id.is_(None))
            )
        if conversation_type is not None:
            statement = statement.where(
                (Conversation.external_conversation_type == conversation_type)
                | (Conversation.external_conversation_type.is_(None))
            )
        conversation = db.scalars(
            statement
            .order_by(
                Conversation.updated_at.desc(),
                Conversation.created_at.desc(),
                Conversation.id.desc(),
            )
        ).first()
        if conversation is not None:
            changed = False
            if channel_config_id is not None and conversation.channel_config_id is None:
                conversation.channel_config_id = channel_config_id
                changed = True
            if conversation_type is not None and conversation.external_conversation_type is None:
                conversation.external_conversation_type = conversation_type
                changed = True
            if changed:
                db.commit()
                db.refresh(conversation)
        return conversation

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
        channel_config_id: str | None = None,
        external_conversation_type: str | None = None,
    ) -> Conversation:
        if character_id is not None:
            from .identity_repository import IdentityRepository
            workspace = IdentityRepository().for_agent(db, character_id)
            if identity_id is not None and identity_id != workspace.id:
                raise ValueError("会话与智能体记忆工作区不一致")
            identity_id = workspace.id
        conversation = Conversation(
            id=str(uuid4()),
            title=title,
            channel=channel,
            character_id=character_id,
            external_user_id=external_user_id,
            model_id=model_id,
            identity_id=identity_id,
            channel_config_id=channel_config_id,
            external_conversation_type=external_conversation_type,
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
