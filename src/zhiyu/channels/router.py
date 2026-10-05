"""Route normalized channel messages through the shared chat service."""

from zhiyu.application.chat import ChatRequest, ChatService, default_chat_service

from .base import IncomingMessage
from .messages import InboundEvent


class ChannelRouter:
    def __init__(self, chat_service: ChatService = default_chat_service) -> None:
        self.chat_service = chat_service

    async def handle(self, message: InboundEvent | IncomingMessage) -> str:
        event = message.to_event() if isinstance(message, IncomingMessage) else message
        result = await self.chat_service.complete(
            ChatRequest(
                message=event.text,
                channel=event.channel,
                external_user_id=event.sender_id,
                external_conversation_id=event.conversation_id,
            )
        )
        return result.response

    async def new_session(self, message: InboundEvent | IncomingMessage) -> str:
        event = message.to_event() if isinstance(message, IncomingMessage) else message
        if event.channel != "qq" or event.conversation_type != "private":
            raise ValueError("仅支持 QQ 私聊新建 Session")
        self.chat_service.new_channel_session(
            event.channel,
            event.sender_id,
            event.conversation_id,
        )
        return "已开启新的对话。"
