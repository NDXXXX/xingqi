"""MCP and Skill API request schemas."""

from pydantic import BaseModel, Field


class McpCreateBody(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: str | None = None
    enabled: bool = False


class McpEnabledBody(BaseModel):
    enabled: bool


class McpEnvBody(BaseModel):
    key: str
    value: str | None = None
    secret: bool = False


class McpSecretBody(BaseModel):
    name: str
    value: str | None = None


class McpAllowlistBody(BaseModel):
    values: list[str] = Field(default_factory=list)
    allow_all: bool = False


class McpReadBody(BaseModel):
    uri: str


class McpPromptBody(BaseModel):
    prompt: str
    arguments: dict[str, str] = Field(default_factory=dict)


class SkillInstallBody(BaseModel):
    source: str
    ref: str | None = None
    subdir: str | None = None


class SkillUpdateBody(BaseModel):
    ref: str | None = None
