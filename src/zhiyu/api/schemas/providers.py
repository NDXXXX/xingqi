"""Provider API request schemas."""

from pydantic import BaseModel, Field


class ProviderCreateBody(BaseModel):
    name: str
    provider_type: str
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None


class ProviderTestBody(BaseModel):
    model: str | None = None


class ProviderDefaultBody(BaseModel):
    provider: str
    model: str


class ProviderUpdateBody(BaseModel):
    base_url: str | None = None
    enabled: bool = True
    api_key: str | None = None
    api_key_env: str | None = None
    clear_api_key: bool = False


class ProviderFallbackBody(BaseModel):
    providers: list[str] = Field(default_factory=list)


class ModelBody(BaseModel):
    model_name: str
    display_name: str | None = None
    enabled: bool = True
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    context_window: int | None = None
    max_output_tokens: int | None = None


class ModelUpdateBody(BaseModel):
    model_name: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
