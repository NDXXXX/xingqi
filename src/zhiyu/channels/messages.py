"""渠道无关的入站事件、消息组件与投递结果。"""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    source: str
    mime_type: str | None = None


class AudioPart(BaseModel):
    type: Literal["audio"] = "audio"
    source: str
    mime_type: str | None = None


class FilePart(BaseModel):
    type: Literal["file"] = "file"
    source: str
    name: str | None = None
    mime_type: str | None = None


class MentionPart(BaseModel):
    type: Literal["mention"] = "mention"
    target_id: str
    display_name: str | None = None


class QuotePart(BaseModel):
    type: Literal["quote"] = "quote"
    message_id: str


MessagePart = Annotated[
    TextPart | ImagePart | AudioPart | FilePart | MentionPart | QuotePart,
    Field(discriminator="type"),
]


class InboundEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    channel: str
    account_id: str
    channel_config_id: str | None = None
    conversation_id: str
    conversation_type: Literal["private", "group", "channel"]
    sender_id: str
    sender_name: str | None = None
    message_id: str | None = None
    reply_to_id: str | None = None
    mentioned_agent: bool = False
    parts: list[MessagePart]
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict = Field(default_factory=dict)
    allowed_tools: list[str] | None = None
    system_prompt: str | None = None

    @property
    def text(self) -> str:
        return "".join(part.text for part in self.parts if isinstance(part, TextPart))

    def plain_text(self) -> str:
        return OutboundMessage(
            conversation_id=self.conversation_id,
            conversation_type=self.conversation_type,
            parts=self.parts,
        ).plain_text()

    @property
    def external_user_id(self) -> str:
        """旧 ChannelRouter/测试使用的兼容名称。"""
        return self.sender_id

    @property
    def external_conversation_id(self) -> str:
        """旧 ChannelRouter/测试使用的兼容名称。"""
        return self.conversation_id


class OutboundMessage(BaseModel):
    conversation_id: str
    conversation_type: Literal["private", "group", "channel"] = "private"
    source_event_id: str | None = None
    reply_to_id: str | None = None
    parts: list[MessagePart]

    @classmethod
    def text(
        cls,
        conversation_id: str,
        content: str,
        *,
        conversation_type: Literal["private", "group", "channel"] = "private",
        source_event_id: str | None = None,
    ) -> "OutboundMessage":
        return cls(
            conversation_id=conversation_id,
            conversation_type=conversation_type,
            source_event_id=source_event_id,
            parts=[TextPart(text=content)],
        )

    def plain_text(self) -> str:
        """为仅支持文本的渠道提供不泄露资源地址的安全降级。"""
        rendered: list[str] = []
        for part in self.parts:
            if isinstance(part, TextPart):
                rendered.append(part.text)
            elif isinstance(part, MentionPart):
                rendered.append(f"@{part.display_name or part.target_id}")
            elif isinstance(part, QuotePart):
                rendered.append("[引用消息]")
            elif isinstance(part, ImagePart):
                rendered.append("[图片]")
            elif isinstance(part, AudioPart):
                rendered.append("[语音]")
            elif isinstance(part, FilePart):
                rendered.append(f"[文件{f': {part.name}' if part.name else ''}]")
        return "".join(rendered)


class DeliveryReceipt(BaseModel):
    delivery_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["sent", "failed", "unknown"]
    provider_message_id: str | None = None
    error: str | None = None
