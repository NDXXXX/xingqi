"""Route normalized channel messages through the shared chat service."""

from zhiyu.application.chat import ChatRequest, ChatService, default_chat_service

from .base import IncomingMessage


class ChannelRouter:
    def __init__(self, chat_service: ChatService = default_chat_service) -> None:
        self.chat_service = chat_service

    async def handle(self, message: IncomingMessage) -> str:
        result = await self.chat_service.complete(
            ChatRequest(
                message=message.text,
                channel=message.channel,
                external_user_id=message.external_user_id,
                external_conversation_id=message.external_conversation_id,
            )
        )
        return result.response
