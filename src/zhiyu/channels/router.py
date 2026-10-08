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
                message=event.plain_text(),
                channel=event.channel,
                external_user_id=event.sender_id,
                external_conversation_id=event.conversation_id,
                external_conversation_type=event.conversation_type,
                channel_config_id=event.channel_config_id,
                channel_event_id=event.event_id,
                parts=event.parts,
                allowed_tools=event.allowed_tools,
                system_prompt=event.system_prompt,
            )
        )
        return result.response

    async def new_session(self, message: InboundEvent | IncomingMessage) -> str:
        event = message.to_event() if isinstance(message, IncomingMessage) else message
        if event.channel != "qq":
            raise ValueError("目前仅支持 QQ 新建 Session")
        self.chat_service.new_channel_session(
            event.channel,
            event.sender_id,
            event.conversation_id,
            channel_config_id=event.channel_config_id,
            conversation_type=event.conversation_type,
        )
        return "已开启新的对话。"

    async def stop_session(self, message: InboundEvent | IncomingMessage) -> str:
        event = message.to_event() if isinstance(message, IncomingMessage) else message
        stopped = self.chat_service.cancel_channel_run(
            event.channel,
            event.conversation_id,
            channel_config_id=event.channel_config_id,
            conversation_type=event.conversation_type,
        )
        return "已停止当前回复。" if stopped else "当前会话没有运行中的回复。"
