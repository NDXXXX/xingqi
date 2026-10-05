"""Conversation and Agent orchestration independent from any user interface."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from zhiyu.core.agent.context import build_tool_registry, with_agent_context_async
from zhiyu.core.agent.run_manager import active_runs
from zhiyu.core.agent.runtime import run_agent, run_agent_stream
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.application.memory_jobs import MemoryJobProcessor
from zhiyu.application.providers import PROVIDER_FALLBACKS_KEY
from zhiyu.core.providers.base import AIProvider
from zhiyu.core.providers.router import ProviderRouter, provider_router
from zhiyu.core.providers.selection import ProviderSelectionError, select_provider_model
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository
from zhiyu.integrations.mcp.manager import McpManager, default_manager as default_mcp_manager


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


@dataclass(slots=True)
class _PreparedChat:
    conversation_id: str
    identity_id: str | None
    provider: AIProvider
    provider_id: str
    model: str
    supports_tools: bool
    supports_streaming: bool
    max_output_tokens: int | None
    fallbacks: list[tuple[str, AIProvider, str]]
    messages: list[dict]
    user_message_id: str


class ChatService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        providers: ProviderRouter = provider_router,
        memory_manager: MemoryManager | None = None,
        memory_processor: MemoryJobProcessor | None = None,
        mcp_manager: McpManager = default_mcp_manager,
    ) -> None:
        self.session_factory = session_factory
        self.providers = providers
        self.memory_processor = memory_processor or MemoryJobProcessor(
            session_factory, providers, memory_manager
        )
        self.mcp_manager = mcp_manager
        self.conversations = ConversationRepository()
        self.messages = MessageRepository()
        self.memory_jobs = MemoryJobRepository()
        self.identities = IdentityRepository()
        self.channel_configs = ChannelConfigRepository()
        self.provider_configs = ProviderRepository()
        self.settings = SettingRepository()
        self.runs = AgentRunRepository()

    async def _prepare(self, db: Session, request: ChatRequest):
        if request.channel == "qq":
            if not request.external_user_id:
                raise ValueError("QQ 消息缺少发送者 ID")
            self._require_qq_owner(db, request.external_user_id)
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
            if request.channel == "qq":
                identity = self.identities.local(db)
            else:
                identity = self.identities.get_or_create(
                    db, request.channel, request.external_user_id
                )
            conversation_key = request.external_conversation_id or request.external_user_id
            conversation = self.conversations.get_by_external(db, request.channel, conversation_key)
            if conversation is None:
                conversation = self.conversations.create(
                    db,
                    title=request.message.strip()[:30] or "New Chat",
                    channel=request.channel,
                    external_user_id=conversation_key,
                    identity_id=identity.id,
                )
            elif request.channel == "qq" and conversation.identity_id != identity.id:
                conversation.identity_id = identity.id
                db.commit()
            elif conversation.identity_id is None:
                conversation.identity_id = identity.id
                db.commit()

        if conversation.identity_id is None and conversation.channel == "local":
            conversation.identity_id = self.identities.local(db).id
            db.commit()

        memory_manager = self.memory_processor.memory_manager
        if isinstance(memory_manager, MemoryManager) and conversation.identity_id:
            try:
                rebuild_index(db, memory_manager.store, conversation.identity_id)
            except Exception as exc:
                db.rollback()
                logger.warning("memory index recovery degraded: %s", exc)

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
            user_message = self.messages.create(
                db,
                conversation_id=conversation.id,
                role="user",
                content=request.message,
            )

        history = self.messages.list_by_conversation(db, conversation.id)
        llm_messages = [{"role": item.role, "content": item.content} for item in history]
        llm_messages = await with_agent_context_async(
            db,
            conversation,
            request.message,
            llm_messages,
            model_config.context_window,
            model_config.max_output_tokens,
            recall=None,
        )
        fallback_mapping = self.settings.get(db, PROVIDER_FALLBACKS_KEY) or {}
        if not isinstance(fallback_mapping, dict):
            fallback_mapping = {}
        configured_fallbacks = fallback_mapping.get(provider.id, [])
        if not isinstance(configured_fallbacks, list):
            configured_fallbacks = []
        fallbacks: list[tuple[str, AIProvider, str]] = []
        for fallback_id in configured_fallbacks:
            if not isinstance(fallback_id, str):
                continue
            fallback_config = self.provider_configs.get(db, fallback_id)
            if fallback_config is None or not fallback_config.enabled or not fallback_config.configured:
                continue
            fallback_model = next(
                (item for item in fallback_config.models if item.enabled),
                None,
            )
            if fallback_model is None:
                continue
            fallbacks.append(
                (
                    fallback_config.id,
                    self.providers.get_provider(fallback_config),
                    fallback_model.model_name,
                )
            )

        return _PreparedChat(
            conversation_id=conversation.id,
            identity_id=conversation.identity_id,
            provider=self.providers.get_provider(provider),
            provider_id=provider.id,
            model=model_config.model_name,
            supports_tools=model_config.supports_tools,
            supports_streaming=model_config.supports_streaming,
            max_output_tokens=model_config.max_output_tokens,
            fallbacks=fallbacks,
            messages=llm_messages,
            user_message_id=user_message.id,
        )

    def new_channel_session(
        self, channel: str, external_user_id: str, external_conversation_id: str
    ):
        """Start an empty channel conversation while retaining the Agent memory identity."""
        if channel != "qq":
            raise ValueError("目前仅支持 QQ 新建 Session")
        if not external_user_id or not external_conversation_id:
            raise ValueError("外部渠道消息缺少用户或会话 ID")
        with self.session_factory() as db:
            self._require_qq_owner(db, external_user_id)
            return self.conversations.create(
                db,
                title="QQ 新会话",
                channel=channel,
                external_user_id=external_conversation_id,
                identity_id=self.identities.local(db).id,
            )

    def _require_qq_owner(self, db: Session, external_user_id: str) -> None:
        config = self.channel_configs.get(db, "qq")
        if config is None or not config.owner_user_id:
            raise ValueError("QQ 未配置主人 ID，拒绝访问个人 Agent")
        if external_user_id != config.owner_user_id:
            raise ValueError("该 QQ 账号未获准使用个人 Agent")

    async def run(
        self,
        request: ChatRequest,
        *,
        streaming: bool = True,
    ) -> AsyncGenerator[dict, None]:
        run_id: str | None = None
        try:
            with self.session_factory() as db:
                prepared = await self._prepare(db, request)
                run = self.runs.create(
                    db,
                    prepared.conversation_id,
                    prepared.provider_id,
                    prepared.model,
                )
                run_id = run.id
            registry = build_tool_registry(self.mcp_manager)
            active_runs.register(run_id)
            yield {
                "type": "run",
                "run_id": run_id,
                "conversation_id": prepared.conversation_id,
            }

            final_response = ""
            prompt_tokens: int | None = None
            completion_tokens: int | None = None
            final_provider_id = prepared.provider_id
            final_model = prepared.model
            runner = run_agent_stream if streaming else run_agent
            runner_options = {
                "supports_tools": prepared.supports_tools,
                "max_output_tokens": prepared.max_output_tokens,
                "provider_id": prepared.provider_id,
                "fallbacks": prepared.fallbacks,
            }
            if streaming:
                runner_options["supports_streaming"] = prepared.supports_streaming
            async for event in runner(
                prepared.provider,
                registry,
                prepared.model,
                prepared.conversation_id,
                prepared.messages,
                **runner_options,
            ):
                if event["type"] in {"step", "tool"}:
                    with self.session_factory() as event_db:
                        self.runs.add_event(event_db, run_id, event)
                elif event["type"] == "final":
                    final_response = event["final_response"]
                    prompt_tokens = event.get("prompt_tokens")
                    completion_tokens = event.get("completion_tokens")
                    final_provider_id = event.get("provider_id") or prepared.provider_id
                    final_model = event.get("model") or prepared.model
                yield event

            with self.session_factory() as db:
                assistant_message = self.messages.create(
                    db,
                    conversation_id=prepared.conversation_id,
                    role="assistant",
                    content=final_response,
                    commit=False,
                )
                if not request.regenerate and prepared.identity_id:
                    self.memory_jobs.create(
                        db,
                        user_message_id=prepared.user_message_id,
                        assistant_message_id=assistant_message.id,
                        identity_id=prepared.identity_id,
                        provider_id=final_provider_id,
                        model=final_model,
                    )
                db.commit()
                self.conversations.touch(
                    db,
                    prepared.conversation_id,
                    final_model,
                )
                self.runs.finish(
                    db,
                    run_id,
                    "completed",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    provider_id=final_provider_id,
                    model_id=final_model,
                )
            self.memory_processor.kick()
            yield {
                "type": "done",
                "run_id": run_id,
                "conversation_id": prepared.conversation_id,
                "response": final_response,
            }
        except asyncio.CancelledError:
            if run_id is not None:
                with self.session_factory() as db:
                    self.runs.finish(db, run_id, "cancelled")
            raise
        except Exception as exc:
            if run_id is not None:
                with self.session_factory() as db:
                    self.runs.finish(db, run_id, "failed", str(exc))
            raise
        finally:
            if run_id is not None:
                active_runs.unregister(run_id)

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
