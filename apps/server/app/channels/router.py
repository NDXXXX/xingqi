"""Channel Router：把 IncomingMessage 转成 Agent 调用并返回回复。"""

import logging

from sqlalchemy.orm import Session

from ..agent.context import build_tool_registry, with_agent_context
from ..agent.runtime import run_agent
from ..database.db import SessionLocal
from ..database.repositories.conversation_repository import ConversationRepository
from ..database.repositories.message_repository import MessageRepository
from ..database.repositories.identity_repository import IdentityRepository
from ..database.repositories.agent_run_repository import AgentRunRepository
from ..memory.manager import MemoryManager
from ..providers.router import provider_router
from ..providers.selection import ProviderSelectionError, select_provider_model
from .base import IncomingMessage

logger = logging.getLogger(__name__)


class ChannelRouter:
    """外部渠道消息 → 查找/创建会话 → Agent → 回复文本。"""

    def __init__(self) -> None:
        self.conversation_repo = ConversationRepository()
        self.message_repo = MessageRepository()
        self.memory_manager = MemoryManager()
        self.identity_repo = IdentityRepository()
        self.run_repo = AgentRunRepository()

    async def handle(self, message: IncomingMessage) -> str:
        db = SessionLocal()
        try:
            conversation = self.conversation_repo.get_by_external(
                db, message.channel, message.external_user_id
            )
            identity = self.identity_repo.get_or_create(
                db, message.channel, message.external_user_id
            )
            if conversation is None:
                title = message.text.strip()[:30] or "New Chat"
                conversation = self.conversation_repo.create(
                    db,
                    title=title,
                    channel=message.channel,
                    external_user_id=message.external_user_id,
                    identity_id=identity.id,
                )
            elif conversation.identity_id is None:
                conversation.identity_id = identity.id
                db.commit()
            try:
                provider, model_config = select_provider_model(db, conversation)
            except ProviderSelectionError as e:
                raise RuntimeError(str(e)) from e
            model = model_config.model_name

            self.message_repo.create(
                db, conversation_id=conversation.id, role="user", content=message.text
            )
            history = self.message_repo.list_by_conversation(db, conversation.id)
            llm_messages = [{"role": m.role, "content": m.content} for m in history]
            llm_messages = with_agent_context(
                db,
                conversation,
                message.text,
                llm_messages,
                model_config.context_window,
                model_config.max_output_tokens,
            )

            p = provider_router.get_provider(provider)
            registry = build_tool_registry()
            run = self.run_repo.create(db, conversation.id, provider.id, model)
            final_response = ""
            try:
                async for event in run_agent(p, registry, model, conversation.id, llm_messages):
                    if event["type"] in {"step", "tool"}:
                        self.run_repo.add_event(db, run.id, event)
                    elif event["type"] == "final":
                        final_response = event["final_response"]
            except Exception as exc:
                self.run_repo.finish(db, run.id, "failed", str(exc))
                raise

            self.message_repo.create(
                db, conversation_id=conversation.id, role="assistant", content=final_response
            )
            self.conversation_repo.touch(db, conversation.id, model)
            try:
                await self.memory_manager.extract_and_save(
                    db, p, model, message.text, final_response, identity.id
                )
            except Exception as e:
                logger.warning("memory extraction failed: %s", e)
            self.run_repo.finish(db, run.id, "completed")
            return final_response
        finally:
            db.close()
