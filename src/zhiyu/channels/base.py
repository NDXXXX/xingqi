"""Channel 抽象与旧文本消息兼容入口。"""

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from .messages import DeliveryReceipt, InboundEvent, OutboundMessage, TextPart


class IncomingMessage(BaseModel):
    """旧文本消息格式；新渠道应直接生成 InboundEvent。"""

    channel: str
    external_user_id: str
    external_conversation_id: str
    text: str
    metadata: dict = Field(default_factory=dict)

    def to_event(self) -> InboundEvent:
        conversation_type = self.metadata.get("message_type", "private")
        if conversation_type not in {"private", "group", "channel"}:
            conversation_type = "private"
        return InboundEvent(
            channel=self.channel,
            account_id=str(self.metadata.get("account_id", f"{self.channel}-default")),
            conversation_id=self.external_conversation_id,
            conversation_type=conversation_type,
            sender_id=self.external_user_id,
            message_id=self.metadata.get("message_id"),
            mentioned_agent=bool(self.metadata.get("mentioned_agent", False)),
            parts=[TextPart(text=self.text)],
            raw=self.metadata,
        )


class ChannelAdapter(ABC):
    """所有渠道适配器的统一接口（§24）。"""

    name: str = ""

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> DeliveryReceipt:
        ...

    async def send_message(self, target: str, message: str) -> DeliveryReceipt:
        """兼容旧调用方，内部统一转换成 OutboundMessage。"""
        return await self.send(OutboundMessage.text(target, message))
