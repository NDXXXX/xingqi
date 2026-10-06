"""Channel API request schemas."""

from pydantic import BaseModel, Field


class QQConfigureBody(BaseModel):
    endpoint: str
    token: str | None = None
    owner_user_id: str | None = None


class QQGroupBody(BaseModel):
    enabled: bool
    require_mention: bool = True
    tool_allowlist: list[str] = Field(default_factory=list)
    system_prompt: str | None = None


class DeliveryRetryBody(BaseModel):
    allow_unknown: bool = False
