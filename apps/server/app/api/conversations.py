"""Conversation / Message API。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..database.db import get_db
from ..database.models import Conversation, Message
from ..database.repositories.conversation_repository import ConversationRepository
from ..database.repositories.message_repository import MessageRepository

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

conversation_repo = ConversationRepository()
message_repo = MessageRepository()


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationCreate(BaseModel):
    title: str = "New Chat"
    channel: str = "desktop"
    character_id: str | None = None
    external_user_id: str | None = None
    model_id: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    character_id: str | None
    channel: str
    external_user_id: str | None
    model_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)) -> list[Conversation]:
    return conversation_repo.list(db)


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(payload: ConversationCreate, db: Session = Depends(get_db)) -> Conversation:
    return conversation_repo.create(
        db,
        title=payload.title,
        channel=payload.channel,
        character_id=payload.character_id,
        external_user_id=payload.external_user_id,
        model_id=payload.model_id,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> Conversation:
    conversation = conversation_repo.get(db, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, db: Session = Depends(get_db)) -> None:
    if not conversation_repo.delete(db, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: str, db: Session = Depends(get_db)) -> list[Message]:
    if conversation_repo.get(db, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return message_repo.list_by_conversation(db, conversation_id)
