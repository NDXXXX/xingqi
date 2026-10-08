"""Shared chat orchestration without FastAPI."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.channels.messages import ImagePart, TextPart
from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


class FakeProvider(AIProvider):
    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content="你好，测试完成")

    async def stream_chat(self, messages, tools=None, **kwargs):
        yield "你好，"
        yield "测试完成"
        yield LLMResponse(content="你好，测试完成")


class FakeRouter:
    def get_provider(self, _provider):
        return FakeProvider("fake-key")


async def test_new_chat_without_provider_does_not_create_empty_conversation():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    service = ChatService(sessions, FakeRouter(), AsyncMock())

    with pytest.raises(ValueError, match="没有可用的 Provider"):
        async for _event in service.run(ChatRequest(message="你好")):
            pass

    with sessions() as db:
        conversations = ConversationRepository().list(db)

    assert conversations == []


async def test_chat_stream_persists_messages_and_run():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db,
            name="Fake",
            provider_type="openai",
            api_key_ref="env:FAKE_KEY",
            base_url="http://example.invalid",
        )
        model = provider.models[0]

    memory = AsyncMock()
    service = ChatService(sessions, FakeRouter(), memory)
    events = [
        event
        async for event in service.run(
            ChatRequest(
                message="你好",
                provider_id=provider.id,
                model=model.model_name,
            )
        )
    ]
    done = next(event for event in events if event["type"] == "done")
    await service.memory_processor.wait_idle()

    with sessions() as db:
        messages = MessageRepository().list_by_conversation(db, done["conversation_id"])
        runs = AgentRunRepository().list_for_conversation(db, done["conversation_id"])
        conversation = db.get(models.Conversation, done["conversation_id"])
        jobs = MemoryJobRepository().list_by_status(db, "completed")

    assert [event["text"] for event in events if event["type"] == "chunk"] == [
        "你好，",
        "测试完成",
    ]
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[-1].content == "你好，测试完成"
    assert runs[0].status == "completed"
    assert conversation.channel == "local"
    assert len(jobs) == 1
    memory.extract_and_save.assert_awaited_once()

    memory.reset_mock()
    await service.complete(
        ChatRequest(
            message="ignored",
            conversation_id=done["conversation_id"],
            provider_id=provider.id,
            model=model.model_name,
            regenerate=True,
        )
    )
    await service.memory_processor.wait_idle()
    memory.extract_and_save.assert_not_awaited()


async def test_chat_done_does_not_wait_for_memory_extraction():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider.id
        model_name = provider.models[0].model_name

    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingMemoryManager:
        async def extract_and_save(self, *_args, **_kwargs):
            started.set()
            await release.wait()
            return []

    service = ChatService(sessions, FakeRouter(), BlockingMemoryManager())
    result = await asyncio.wait_for(
        service.complete(
            ChatRequest(message="你好", provider_id=provider_id, model=model_name)
        ),
        timeout=1,
    )

    assert result.response == "你好，测试完成"
    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    await service.memory_processor.wait_idle()


async def test_explicit_assistant_rename_is_used_on_same_and_next_turn(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider.id
        model = provider.models[0].model_name

    class CapturingProvider(FakeProvider):
        def __init__(self):
            super().__init__("fake-key")
            self.prompts = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            self.prompts.append(messages)
            return await super().chat(messages, tools=tools, stream=stream, **kwargs)

    class Router:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    captured = CapturingProvider()
    store = MemoryStore(tmp_path)
    service = ChatService(sessions, Router(captured), MemoryManager(store))
    first = await service.complete(ChatRequest(
        message="命名Harry", provider_id=provider_id, model=model
    ))
    assert "你的名字是“Harry”" in str(captured.prompts[0])
    await service.memory_processor.wait_idle()

    await service.complete(ChatRequest(
        message="你叫什么", conversation_id=first.conversation_id,
        provider_id=provider_id, model=model,
    ))
    assert "你的名字是“Harry”" in str(captured.prompts[-1])
    await service.memory_processor.wait_idle()

    await service.complete(ChatRequest(
        message="改名字叫Mini", provider_id=provider_id, model=model,
    ))
    assert "你的名字是“Mini”" in str(captured.prompts[-1])
    await service.memory_processor.wait_idle()

    await service.complete(ChatRequest(
        message="你叫什么", provider_id=provider_id, model=model,
    ))
    assert "你的名字是“Mini”" in str(captured.prompts[-1])
    assert "你的名字是“Harry”" not in str(captured.prompts[-1])
    await service.memory_processor.wait_idle()
    with sessions() as db:
        identity_id = IdentityRepository().local(db).id
    assert [entry.content for entry in store.read_entries(store.identity_path_for(identity_id))] == [
        "助手名字是 Mini"
    ]


async def test_explicit_remember_is_available_in_same_turn(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        config = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id, model_name = config.id, config.models[0].model_name

    class CapturingProvider(FakeProvider):
        def __init__(self):
            super().__init__("fake-key")
            self.agent_messages = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            if "情景记忆提取器" in str(messages[0].get("content", "")):
                return LLMResponse(content=(
                    '[{"type":"preference","content":"用户喜欢简洁回答",'
                    '"evidence":"我喜欢简洁回答"}]'
                ))
            self.agent_messages.append(messages)
            return LLMResponse(content="收到")

    class Router:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    provider = CapturingProvider()
    service = ChatService(sessions, Router(provider), MemoryManager(MemoryStore(tmp_path)))
    await service.complete(ChatRequest(
        message="记住我喜欢简洁回答", provider_id=provider_id, model=model_name
    ))
    assert "用户喜欢简洁回答" in str(provider.agent_messages[0])
    await service.memory_processor.wait_idle()


async def test_chat_service_applies_model_capabilities():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider_config = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        model = provider_config.models[0]
        model.supports_tools = False
        model.supports_streaming = False
        model.max_output_tokens = 321
        provider_id = provider_config.id
        model_name = model.model_name
        db.commit()

    class CapturingProvider(AIProvider):
        def __init__(self):
            super().__init__("fake-key")
            self.requests = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            self.requests.append({"tools": tools, "stream": stream, **kwargs})
            return LLMResponse(content="非流式回复")

    class CapturingRouter:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    provider = CapturingProvider()
    service = ChatService(sessions, CapturingRouter(provider), AsyncMock())
    events = [
        event
        async for event in service.run(
            ChatRequest(message="你好", provider_id=provider_id, model=model_name)
        )
    ]
    await service.memory_processor.wait_idle()

    assert [event["text"] for event in events if event["type"] == "chunk"] == ["非流式回复"]
    assert provider.requests[0] == {
        "tools": None,
        "stream": False,
        "model": model_name,
        "max_output_tokens": 321,
    }


async def test_provider_call_does_not_hold_database_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    open_sessions = 0

    class TrackingSession(Session):
        def __init__(self, *args, **kwargs):
            nonlocal open_sessions
            super().__init__(*args, **kwargs)
            self._tracking_closed = False
            open_sessions += 1

        def close(self):
            nonlocal open_sessions
            if not self._tracking_closed:
                open_sessions -= 1
                self._tracking_closed = True
            super().close()

    sessions = sessionmaker(
        bind=engine,
        class_=TrackingSession,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(engine)
    with sessions() as db:
        provider_config = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider_config.id
        model_name = provider_config.models[0].model_name

    class CheckingProvider(FakeProvider):
        async def chat(self, messages, tools=None, stream=False, **kwargs):
            assert open_sessions == 0
            return await super().chat(messages, tools, stream, **kwargs)

    class CheckingRouter:
        def get_provider(self, _provider):
            return CheckingProvider("fake-key")

    service = ChatService(sessions, CheckingRouter(), AsyncMock())
    await service.complete(
        ChatRequest(message="你好", provider_id=provider_id, model=model_name)
    )
    await service.memory_processor.wait_idle()

    assert open_sessions == 0


async def test_chat_service_uses_configured_fallback_and_records_usage():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        primary = ProviderRepository().create(
            db, name="Primary", provider_type="openai", api_key_ref="env:PRIMARY_KEY"
        )
        backup = ProviderRepository().create(
            db, name="Backup", provider_type="openai", api_key_ref="env:BACKUP_KEY"
        )
        SettingRepository().set(
            db,
            "provider_fallbacks",
            {primary.id: [backup.id]},
        )
        primary_id = primary.id
        primary_model = primary.models[0].model_name
        backup_id = backup.id
        backup_model = backup.models[0].model_name

    class OfflineProvider(AIProvider):
        async def chat(self, messages, tools=None, stream=False, **kwargs):
            request = httpx.Request("POST", "https://offline.invalid")
            raise httpx.ConnectError("offline", request=request)

    class UsageProvider(AIProvider):
        async def chat(self, messages, tools=None, stream=False, **kwargs):
            return LLMResponse(
                content="备用回复",
                prompt_tokens=21,
                completion_tokens=5,
            )

    class RoutingProvider:
        def get_provider(self, config):
            if config.id == primary_id:
                return OfflineProvider("primary")
            return UsageProvider("backup")

    service = ChatService(sessions, RoutingProvider(), AsyncMock())
    result = await service.complete(
        ChatRequest(
            message="你好",
            provider_id=primary_id,
            model=primary_model,
        )
    )
    await service.memory_processor.wait_idle()

    with sessions() as db:
        run = AgentRunRepository().list_for_conversation(db, result.conversation_id)[0]
        jobs = MemoryJobRepository().list_by_status(db, "completed")
    assert result.response == "备用回复"
    assert run.provider_id == backup_id
    assert run.model_id == backup_model
    assert run.prompt_tokens == 21
    assert run.completion_tokens == 5
    assert jobs[0].provider_id == backup_id


async def test_channel_conversation_key_is_separate_from_identity():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db,
            name="Fake",
            provider_type="openai",
            api_key_ref="env:FAKE_KEY",
        )
        ChannelConfigRepository().upsert(
            db, "qq", "ws://localhost:6199/ws", None, owner_user_id="u1"
        )
    service = ChatService(sessions, FakeRouter(), AsyncMock())
    first = await service.complete(ChatRequest(
        message="one", channel="qq", external_user_id="u1", external_conversation_id="group-1"
    ))
    second = await service.complete(ChatRequest(
        message="two", channel="qq", external_user_id="u1", external_conversation_id="group-2"
    ))
    await service.memory_processor.wait_idle()
    assert first.conversation_id != second.conversation_id
    with sessions() as db:
        first_conversation = ConversationRepository().get(db, first.conversation_id)
        second_conversation = ConversationRepository().get(db, second.conversation_id)
        local_identity = IdentityRepository().local(db)
        assert first_conversation.identity_id == local_identity.id
        assert second_conversation.identity_id == local_identity.id
        assert MemoryJobRepository().list_by_status(db, "pending") == []


async def test_unauthorized_qq_sender_is_rejected_before_conversation_creation():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        ChannelConfigRepository().upsert(
            db, "qq", "ws://localhost:6199/ws", None, owner_user_id="owner"
        )
    service = ChatService(sessions, FakeRouter(), AsyncMock())

    try:
        await service.complete(
            ChatRequest(
                message="private info",
                channel="qq",
                external_user_id="stranger",
                external_conversation_id="stranger",
            )
        )
    except ValueError as exc:
        assert "未获准" in str(exc)
    else:
        raise AssertionError("unauthorized QQ sender was accepted")

    with sessions() as db:
        assert ConversationRepository().list(db) == []


async def test_channel_event_reuses_completed_agent_run_and_passes_images_to_vision_model():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider_config = ProviderRepository().create(
            db, name="Vision", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        model = provider_config.models[0]
        model.supports_vision = True
        config = ChannelConfigRepository().upsert(
            db, "qq", "ws://127.0.0.1:6199/ws", None, owner_user_id="owner"
        )
        provider_id = provider_config.id
        model_name = model.model_name
        config_id = config.id
        db.commit()

    class CapturingProvider(AIProvider):
        def __init__(self):
            super().__init__("fake")
            self.calls = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            self.calls.append(messages)
            return LLMResponse(content="看到了")

    class Router:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    provider = CapturingProvider()
    service = ChatService(sessions, Router(provider), AsyncMock())
    service.media = type(
        "FakeMedia", (), {"data_url": staticmethod(lambda _source: "data:image/png;base64,AA==")}
    )()
    request = ChatRequest(
        message="看图[图片]",
        channel="qq",
        external_user_id="owner",
        external_conversation_id="owner",
        external_conversation_type="private",
        channel_config_id=config_id,
        channel_event_id="qq:qq-onebot-default:vision-1",
        parts=[TextPart(text="看图"), ImagePart(source="managed://asset")],
        provider_id=provider_id,
        model=model_name,
    )

    first = await service.complete(request)
    second = await service.complete(request)
    await service.memory_processor.wait_idle()

    assert first.run_id == second.run_id
    assert len(provider.calls) == 1
    user_content = next(
        item["content"]
        for item in provider.calls[0]
        if item.get("role") == "user"
    )
    assert [item["type"] for item in user_content] == ["text", "image_url"]


async def test_qq_new_session_keeps_history_separate_and_reuses_shared_identity():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider.id
        model_name = provider.models[0].model_name
        ChannelConfigRepository().upsert(
            db, "qq", "ws://localhost:6199/ws", None, owner_user_id="owner"
        )
    service = ChatService(sessions, FakeRouter(), AsyncMock())

    first = await service.complete(
        ChatRequest(
            message="第一条 session 的内容",
            channel="qq",
            external_user_id="owner",
            external_conversation_id="owner",
            provider_id=provider_id,
            model=model_name,
        )
    )
    new_conversation = service.new_channel_session("qq", "owner", "owner")
    second = await service.complete(
        ChatRequest(
            message="第二条 session 的内容",
            channel="qq",
            external_user_id="owner",
            external_conversation_id="owner",
            provider_id=provider_id,
            model=model_name,
        )
    )
    await service.memory_processor.wait_idle()

    with sessions() as db:
        first_messages = MessageRepository().list_by_conversation(db, first.conversation_id)
        second_messages = MessageRepository().list_by_conversation(db, second.conversation_id)
        current = ConversationRepository().get_by_external(db, "qq", "owner")
        assert first.conversation_id != new_conversation.id
        assert second.conversation_id == new_conversation.id
        assert current.id == new_conversation.id
        assert all("第二条" not in message.content for message in first_messages)
        assert all("第一条" not in message.content for message in second_messages)
        assert {item.identity_id for item in (current, ConversationRepository().get(db, first.conversation_id))} == {
            IdentityRepository().local(db).id
        }


async def test_local_and_qq_share_memories_without_sharing_transcripts(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider_config = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider_config.id
        model_name = provider_config.models[0].model_name
        ChannelConfigRepository().upsert(
            db, "qq", "ws://localhost:6199/ws", None, owner_user_id="owner"
        )

    class MemoryAwareProvider(AIProvider):
        def __init__(self):
            super().__init__("fake-key")
            self.agent_messages = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            prompt = str(messages[0].get("content", "")) if messages else ""
            if "情景记忆提取器" in prompt:
                if "我的代号是星河" in prompt:
                    return LLMResponse(content=(
                        '[{"type":"profile","content":"用户的代号是星河",'
                        '"evidence":"我的代号是星河"}]'
                    ))
                return LLMResponse(content="[]")
            self.agent_messages.append(messages)
            return LLMResponse(content="收到")

    class CapturingRouter:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    store = MemoryStore(tmp_path)
    provider = MemoryAwareProvider()
    service = ChatService(
        sessions,
        CapturingRouter(provider),
        MemoryManager(store),
    )
    MemoryService(sessions, store=store).add(
        type="preference", content="用户喜欢爵士乐"
    )

    await service.complete(ChatRequest(
        message="我喜欢什么音乐？",
        channel="qq",
        external_user_id="owner",
        external_conversation_id="owner",
        external_conversation_type="private",
        provider_id=provider_id,
        model=model_name,
    ))
    assert "用户喜欢爵士乐" in str(provider.agent_messages[-1])

    await service.complete(ChatRequest(
        message="我的代号是星河；蓝鲸口令只留在这条原始记录里",
        channel="qq",
        external_user_id="owner",
        external_conversation_id="owner",
        external_conversation_type="private",
        provider_id=provider_id,
        model=model_name,
    ))
    await service.memory_processor.wait_idle()

    await service.complete(ChatRequest(
        message="我的代号是什么？",
        provider_id=provider_id,
        model=model_name,
    ))
    local_context = str(provider.agent_messages[-1])
    assert "用户的代号是星河" in local_context
    assert "蓝鲸口令" not in local_context
