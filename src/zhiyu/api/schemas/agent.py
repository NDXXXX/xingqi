"""Chat and memory API request schemas."""

from pydantic import BaseModel


class ChatBody(BaseModel):
    message: str
    conversation_id: str | None = None
    provider_id: str | None = None
    model: str | None = None


class MemoryEditBody(BaseModel):
    content: str
