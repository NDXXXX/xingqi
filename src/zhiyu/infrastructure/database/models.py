"""ORM 模型：Conversation、Message、Provider、ModelConfig。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """返回 naive UTC 时间（SQLite 不保存时区）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    character_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="local")
    channel_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_conversation_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identities.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    parts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    content: Mapped[str] = mapped_column(Text)
    source_message_count: Mapped[int] = mapped_column(Integer)
    last_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_message_created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Provider(Base):
    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    provider_type: Mapped[str] = mapped_column(String(32))
    api_key_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    models: Mapped[list["ModelConfig"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )

    @property
    def configured(self) -> bool:
        return self.api_key_ref is not None


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), index=True)
    model_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(nullable=True)

    provider: Mapped["Provider"] = relationship(back_populates="models")


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    background: Mapped[str | None] = mapped_column(Text, nullable=True)
    speaking_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_identity_status", "identity_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    identity_id: Mapped[str | None] = mapped_column(ForeignKey("identities.id"), nullable=True, index=True)
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(32), default="active")
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    status_source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String(32), default="automatic")
    tier: Mapped[str] = mapped_column(String(16), default="core")
    trust: Mapped[str] = mapped_column(String(16), default="agent")
    source_kind: Mapped[str] = mapped_column(String(16), default="message")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    supersession_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trigger_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    promotion_status: Mapped[str] = mapped_column(String(16), default="none")
    promoted_to_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MemoryFileIndex(Base):
    __tablename__ = "memory_file_indexes"
    __table_args__ = (
        UniqueConstraint("identity_id", "file_path", name="uq_memory_file_index_identity_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mtime_ns: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64))
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryJob(Base):
    __tablename__ = "memory_jobs"
    __table_args__ = (
        UniqueConstraint("user_message_id", name="uq_memory_jobs_user_message"),
        Index("ix_memory_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MemoryConsolidationRun(Base):
    __tablename__ = "memory_consolidation_runs"
    __table_args__ = (Index("ix_consolidation_identity_created", "identity_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="applied")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    promoted_count: Mapped[int] = mapped_column(Integer, default=0)
    merged_count: Mapped[int] = mapped_column(Integer, default=0)
    superseded_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MemoryEmbedding(Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (
        UniqueConstraint("memory_id", "model", name="uq_memory_embedding_model"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(255))
    vector_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ForgottenConversation(Base):
    __tablename__ = "forgotten_conversations"
    __table_args__ = (
        UniqueConstraint(
            "identity_id", "conversation_id", name="uq_forgotten_conversation_identity"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemorySource(Base):
    __tablename__ = "memory_sources"
    __table_args__ = (
        UniqueConstraint(
            "memory_id",
            "source_memory_id",
            "source_message_id",
            name="uq_memory_source_lineage",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trust: Mapped[str] = mapped_column(String(16), default="agent")
    source_kind: Mapped[str] = mapped_column(String(32), default="message")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryRecallEvent(Base):
    __tablename__ = "memory_recall_events"
    __table_args__ = (
        Index("ix_memory_recall_identity_created", "identity_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_hash: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    recall_mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StandingIntent(Base):
    __tablename__ = "standing_intents"
    __table_args__ = (
        Index("ix_standing_intents_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    source_conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16))
    topic: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(32))
    channel_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MemoryMutation(Base):
    __tablename__ = "memory_mutations"
    __table_args__ = (
        Index("ix_memory_mutation_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(16))
    relative_path: Mapped[str] = mapped_column(String(500))
    entry_key: Mapped[str] = mapped_column(String(64))
    expected_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_entry_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="prepared")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("channel", "external_user_id", name="uq_identity_channel_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    external_user_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChannelConfig(Base):
    __tablename__ = "channel_configs"
    __table_args__ = (
        UniqueConstraint("channel", "account_id", name="uq_channel_config_account"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    account_id: Mapped[str] = mapped_column(String(255), default="qq-onebot-default")
    driver: Mapped[str] = mapped_column(String(64), default="onebot_reverse_ws")
    name: Mapped[str] = mapped_column(String(255))
    endpoint: Mapped[str] = mapped_column(String(500))
    secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allow_group_messages: Mapped[bool] = mapped_column(Boolean, default=False)
    group_require_mention: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChannelEvent(Base):
    __tablename__ = "channel_events"
    __table_args__ = (
        UniqueConstraint(
            "channel",
            "account_id",
            "external_event_id",
            name="uq_channel_event_external",
        ),
        Index("ix_channel_events_status_received", "status", "received_at"),
    )

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))
    channel_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    account_id: Mapped[str] = mapped_column(String(255))
    external_event_id: Mapped[str] = mapped_column(String(255))
    conversation_key: Mapped[str] = mapped_column(String(1000))
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    response_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    outbound_message_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChannelDelivery(Base):
    __tablename__ = "channel_deliveries"
    __table_args__ = (
        Index("ix_channel_deliveries_event_created", "event_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_events.id", ondelete="SET NULL"), nullable=True
    )
    channel_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    retry_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_deliveries.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[str] = mapped_column(String(255), unique=True)
    message_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChannelGroupPolicy(Base):
    __tablename__ = "channel_group_policies"
    __table_args__ = (
        UniqueConstraint(
            "channel_config_id", "external_group_id", name="uq_channel_group_policy"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_config_id: Mapped[str] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="CASCADE"), index=True
    )
    external_group_id: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    require_mention: Mapped[bool] = mapped_column(Boolean, default=True)
    tool_allowlist_json: Mapped[str] = mapped_column(Text, default="[]")
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ChannelMediaAsset(Base):
    __tablename__ = "channel_media_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    relative_path: Mapped[str] = mapped_column(String(1000), unique=True)
    mime_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class McpServerConfig(Base):
    __tablename__ = "mcp_server_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    transport: Mapped[str] = mapped_column(String(32), default="stdio")
    command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    args_json: Mapped[str] = mapped_column(Text, default="[]")
    url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    env_json: Mapped[str] = mapped_column(Text, default="{}")
    secret_refs_json: Mapped[str] = mapped_column(Text, default="{}")
    tool_allowlist_json: Mapped[str] = mapped_column(Text, default="[]")
    legacy_all_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    resource_allowlist_json: Mapped[str] = mapped_column(Text, default="[]")
    prompt_allowlist_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class McpRuntimeState(Base):
    __tablename__ = "mcp_runtime_states"

    server_config_id: Mapped[str] = mapped_column(
        ForeignKey("mcp_server_configs.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), default="stopped")
    connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    server_info_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class InstalledSkill(Base):
    __tablename__ = "installed_skills"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32))
    source_locator: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_revision: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    installed_path: Mapped[str] = mapped_column(String(1000))
    manifest_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    installed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    channel_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("channel_events.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    response_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"))
    model_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["AgentRunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="AgentRunStep.started_at"
    )
    conversation: Mapped["Conversation"] = relationship(back_populates="runs")


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    step_type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["AgentRun"] = relationship(back_populates="steps")
