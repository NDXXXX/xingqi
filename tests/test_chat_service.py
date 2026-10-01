"""Shared chat orchestration without FastAPI."""

import asyncio
from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.agent_run_repository import AgentRunRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


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
        model = provider.models[0]

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
            ChatRequest(message="你好", provider_id=provider.id, model=model.model_name)
        ),
        timeout=1,
    )

    assert result.response == "你好，测试完成"
    await asyncio.wait_for(started.wait(), timeout=1)
    release.set()
    await service.memory_processor.wait_idle()


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
    service = ChatService(sessions, FakeRouter(), AsyncMock())
    first = await service.complete(ChatRequest(
        message="one", channel="qq", external_user_id="u1", external_conversation_id="group-1"
    ))
    second = await service.complete(ChatRequest(
        message="two", channel="qq", external_user_id="u1", external_conversation_id="group-2"
    ))
    await service.memory_processor.wait_idle()
    assert first.conversation_id != second.conversation_id
