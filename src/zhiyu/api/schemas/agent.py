"""Chat and memory API request schemas."""

from pydantic import BaseModel


class ChatBody(BaseModel):
    message: str
    conversation_id: str | None = None
    character_id: str | None = None
    provider_id: str | None = None
    model: str | None = None


class MemoryEditBody(BaseModel):
    content: str


class CharacterBody(BaseModel):
    name: str
    description: str | None = None
    personality: str | None = None
    background: str | None = None
    speaking_style: str | None = None
    system_prompt: str | None = None
    default_model_id: str | None = None
