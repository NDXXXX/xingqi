"""Conversation and Agent orchestration independent from any user interface."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
import logging

from sqlalchemy.orm import Session

from zhiyu.core.agent.context import build_tool_registry, with_agent_context
from zhiyu.core.agent.run_manager import active_runs
from zhiyu.core.agent.runtime import run_agent, run_agent_stream
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.recall import build_recall
from zhiyu.core.providers.router import ProviderRouter, provider_router
from zhiyu.core.providers.selection import ProviderSelectionError, select_provider_model
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository

logger = logging.getLogger(__name__)


class ConversationNotFoundError(ValueError):
    pass


@dataclass(slots=True)
class ChatRequest:
    message: str
    conversation_id: str | None = None
    provider_id: str | None = None
    model: str | None = None
    regenerate: bool = False
    channel: str = "local"
    external_user_id: str | None = None
    external_conversation_id: str | None = None


@dataclass(slots=True)
class ChatResult:
    run_id: str
    conversation_id: str
    response: str


class ChatService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        providers: ProviderRouter = provider_router,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.providers = providers
        self.memory_manager = memory_manager or MemoryManager()
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
        self.identities = IdentityRepository()
        self.runs = AgentRunRepository()

    def _prepare(self, db: Session, request: ChatRequest):
        if request.conversation_id:
            conversation = self.conversations.get(db, request.conversation_id)
            if conversation is None:
                raise ConversationNotFoundError("会话不存在")
        elif request.channel == "local":
            conversation = self.conversations.create(
                db,
                title=request.message.strip()[:30] or "New Chat",
                channel="local",
                identity_id=self.identities.local(db).id,
            )
        else:
            if not request.external_user_id:
                raise ValueError("外部渠道消息缺少用户 ID")
            conversation_key = request.external_conversation_id or request.external_user_id
            identity = self.identities.get_or_create(db, request.channel, request.external_user_id)
            conversation = self.conversations.get_by_external(db, request.channel, conversation_key)
            if conversation is None:
                conversation = self.conversations.create(
                    db,
                    title=request.message.strip()[:30] or "New Chat",
                    channel=request.channel,
                    external_user_id=conversation_key,
                    identity_id=identity.id,
                )
            elif conversation.identity_id is None:
                conversation.identity_id = identity.id
                db.commit()

        if conversation.identity_id is None and conversation.channel == "local":
            conversation.identity_id = self.identities.local(db).id
            db.commit()

        try:
            provider, model_config = select_provider_model(
                db,
                conversation,
                request.provider_id,
                request.model,
            )
        except ProviderSelectionError as exc:
            raise ValueError(str(exc)) from exc

        if request.regenerate:
            user_message = self.messages.prepare_regeneration(db, conversation.id)
            if user_message is None:
                raise ValueError("没有可以重新生成的用户消息")
            request.message = user_message.content
        else:
            self.messages.create(
                db,
                conversation_id=conversation.id,
                role="user",
                content=request.message,
            )

        history = self.messages.list_by_conversation(db, conversation.id)
        llm_messages = [{"role": item.role, "content": item.content} for item in history]
        recall = None
        if request.conversation_id is None and request.channel == "local":
            recall = build_recall(
                db, conversation.identity_id, exclude_conversation_id=conversation.id
            )
        llm_messages = with_agent_context(
            db,
            conversation,
            request.message,
            llm_messages,
            model_config.context_window,
            model_config.max_output_tokens,
            recall=recall,
        )
        return conversation, provider, model_config.model_name, llm_messages

    async def run(
        self,
        request: ChatRequest,
        *,
        streaming: bool = True,
    ) -> AsyncGenerator[dict, None]:
        db = self.session_factory()
        run = None
        try:
            conversation, provider_config, model, llm_messages = self._prepare(db, request)
            provider = self.providers.get_provider(provider_config)
            registry = build_tool_registry()
            run = self.runs.create(db, conversation.id, provider_config.id, model)
            active_runs.register(run.id)
            yield {
                "type": "run",
                "run_id": run.id,
                "conversation_id": conversation.id,
            }

            final_response = ""
            runner = run_agent_stream if streaming else run_agent
            async for event in runner(provider, registry, model, conversation.id, llm_messages):
                if event["type"] in {"step", "tool"}:
                    self.runs.add_event(db, run.id, event)
                elif event["type"] == "final":
                    final_response = event["final_response"]
                yield event

            self.messages.create(
                db,
                conversation_id=conversation.id,
                role="assistant",
                content=final_response,
            )
            self.conversations.touch(db, conversation.id, model)
            try:
                await self.memory_manager.extract_and_save(
                    db,
                    provider,
                    model,
                    request.message,
                    final_response,
                    conversation.identity_id,
                )
            except Exception as exc:
                logger.warning("memory extraction failed: %s", exc)
            self.runs.finish(db, run.id, "completed")
            yield {
                "type": "done",
                "run_id": run.id,
                "conversation_id": conversation.id,
                "response": final_response,
            }
        except asyncio.CancelledError:
            if run is not None:
                self.runs.finish(db, run.id, "cancelled")
            raise
        except Exception as exc:
            if run is not None:
                self.runs.finish(db, run.id, "failed", str(exc))
            raise
        finally:
            if run is not None:
                active_runs.unregister(run.id)
            db.close()

    async def complete(self, request: ChatRequest) -> ChatResult:
        result: ChatResult | None = None
        async for event in self.run(request, streaming=False):
            if event["type"] == "done":
                result = ChatResult(
                    run_id=event["run_id"],
                    conversation_id=event["conversation_id"],
                    response=event["response"],
                )
        if result is None:
            raise RuntimeError("Agent 未返回最终结果")
        return result


default_chat_service = ChatService()
