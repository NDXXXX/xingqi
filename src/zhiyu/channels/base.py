"""Channel 抽象：所有聊天渠道统一接口（设计文档 §24-25）。"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class IncomingMessage(BaseModel):
    """所有渠道统一的消息格式（§25）。"""

    channel: str
    external_user_id: str
    external_conversation_id: str
    text: str
    metadata: dict = {}


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
    async def send_message(self, target: str, message: str) -> None:
        ...
