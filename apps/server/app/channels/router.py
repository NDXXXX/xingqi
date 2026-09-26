"""Channel Router：把 IncomingMessage 转成 Agent 调用并返回回复。"""

from sqlalchemy.orm import Session

from ..agent.runtime import run_agent
from ..database.db import SessionLocal
from ..database.models import Provider
from ..database.repositories.conversation_repository import ConversationRepository
from ..database.repositories.message_repository import MessageRepository
from ..database.repositories.provider_repository import ProviderRepository
from ..providers.router import provider_router
from ..tools.registry import default_registry
from .base import IncomingMessage


class ChannelRouter:
    """外部渠道消息 → 查找/创建会话 → Agent → 回复文本。"""

    def __init__(self) -> None:
        self.conversation_repo = ConversationRepository()
        self.message_repo = MessageRepository()
        self.provider_repo = ProviderRepository()

    def _resolve_provider(self, db: Session) -> Provider:
        provider = next((p for p in self.provider_repo.list(db) if p.enabled and p.configured), None)
        if provider is None:
            raise RuntimeError("没有可用的 Provider")
        return provider

    @staticmethod
    def _resolve_model(provider: Provider) -> str:
        if provider.models:
            return provider.models[0].model_name
        raise RuntimeError("Provider 未配置模型")

    async def handle(self, message: IncomingMessage) -> str:
        db = SessionLocal()
        try:
            provider = self._resolve_provider(db)
            model = self._resolve_model(provider)
            conversation = self.conversation_repo.get_by_external(
                db, message.channel, message.external_user_id
            )
            if conversation is None:
                title = message.text.strip()[:30] or "New Chat"
                conversation = self.conversation_repo.create(
                    db,
                    title=title,
                    channel=message.channel,
                    external_user_id=message.external_user_id,
                )

            self.message_repo.create(
                db, conversation_id=conversation.id, role="user", content=message.text
            )
            history = self.message_repo.list_by_conversation(db, conversation.id)
            llm_messages = [{"role": m.role, "content": m.content} for m in history]

            p = provider_router.get_provider(provider)
            registry = default_registry()
            final_response = ""
            async for event in run_agent(p, registry, model, conversation.id, llm_messages):
                if event["type"] == "final":
                    final_response = event["final_response"]

            self.message_repo.create(
                db, conversation_id=conversation.id, role="assistant", content=final_response
            )
            self.conversation_repo.touch(db, conversation.id, model)
            return final_response
        finally:
            db.close()
