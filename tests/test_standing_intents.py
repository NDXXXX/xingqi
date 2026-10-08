"""Owner reminders are deterministic, scoped and forgotten with their source."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.application.memories import MemoryService
from zhiyu.application.runtime import RuntimeHost
from zhiyu.application.standing_intents import StandingIntentService, parse_intent
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import StandingIntent, utcnow
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_parse_event_and_time_reminders():
    assert parse_intent("下次聊部署时提醒我检查变更日志") == (
        "event", "部署", "检查变更日志", None
    )
    parsed = parse_intent(
        "周五上午9点提醒我提交周报",
        now=datetime(2026, 10, 8, 12, tzinfo=timezone.utc),
    )
    assert parsed == ("time", None, "提交周报", datetime(2026, 10, 9, 1))
    assert parse_intent("下次聊部署时提醒我API Key: sk-test-1234567890abcd") is None


def test_event_intent_scope_cooldown_and_forgetting(tmp_path):
    factory = _database()
    service = StandingIntentService()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity.id
        )
        source = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="下次聊部署时提醒我检查变更日志",
        )
        followup = MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content="聊部署"
        )
        assert service.record(db, conversation, source, source.content)
        assert service.due_for_turn(db, conversation, source.content, source.id) == []
        due = service.due_for_turn(db, conversation, followup.content, followup.id)
        assert len(due) == 1
        intent_id, conversation_id = due[0].id, conversation.id
        service.mark_fired(db, [intent_id])
        db.commit()
        assert service.due_for_turn(db, conversation, followup.content, followup.id) == []

    memory = MemoryService(factory, store=MemoryStore(tmp_path))
    assert memory.plan_forget(conversation_id=conversation_id)["intents"][0]["id"] == intent_id
    memory.forget_conversation(conversation_id)
    with factory() as db:
        assert db.scalars(select(StandingIntent).where(StandingIntent.id == intent_id)).first() is None


def test_unknown_qq_conversation_cannot_create_reminder():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="group", channel="qq", identity_id=identity.id,
            external_user_id="123", external_conversation_type="group",
        )
        source = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="下次聊部署时提醒我检查变更日志",
        )
        assert StandingIntentService().record(db, conversation, source, source.content) is None
        assert db.scalars(select(StandingIntent)).all() == []


def test_explicit_cancel_stops_event_reminder():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="local", channel="local", identity_id=identity.id
        )
        source = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="下次聊部署时提醒我检查变更日志",
        )
        cancel = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="取消提醒检查变更日志",
        )
        service = StandingIntentService()
        service.record(db, conversation, source, source.content)
        assert service.record(db, conversation, cancel, cancel.content) == "已取消 1 条提醒"
        assert service.due_for_turn(db, conversation, "聊部署", cancel.id) == []


def test_qq_cancel_only_affects_same_private_target():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        first = ConversationRepository().create(
            db, title="first", channel="qq", identity_id=identity.id,
            external_user_id="123", external_conversation_type="private",
            channel_config_id="bot-a",
        )
        second = ConversationRepository().create(
            db, title="second", channel="qq", identity_id=identity.id,
            external_user_id="456", external_conversation_type="private",
            channel_config_id="bot-b",
        )
        service = StandingIntentService()
        for conversation in (first, second):
            source = MessageRepository().create(
                db, conversation_id=conversation.id, role="user",
                content="下次聊部署时提醒我检查变更日志",
            )
            service.record(db, conversation, source, source.content)
        cancel = MessageRepository().create(
            db, conversation_id=first.id, role="user",
            content="取消提醒检查变更日志",
        )
        assert service.record(db, first, cancel, cancel.content) == "已取消 1 条提醒"
        rows = list(db.scalars(select(StandingIntent)))
        assert {item.target_id: item.status for item in rows} == {
            "123": "cancelled", "456": "active",
        }


async def test_chat_fires_event_reminder_once(tmp_path):
    factory = _database()
    with factory() as db:
        config = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id, model_name = config.id, config.models[0].model_name

    class Provider(AIProvider):
        def __init__(self):
            super().__init__("fake-key")
            self.prompts = []

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            if "情景记忆提取器" in str(messages[0].get("content", "")):
                return LLMResponse(content="[]")
            self.prompts.append(messages)
            return LLMResponse(content="收到")

    class Router:
        def __init__(self, provider):
            self.provider = provider

        def get_provider(self, _config):
            return self.provider

    provider = Provider()
    chat = ChatService(factory, Router(provider), MemoryManager(MemoryStore(tmp_path)))
    chat.memory_processor.kick = lambda: None
    first = await chat.complete(ChatRequest(
        message="下次聊部署时提醒我检查变更日志",
        provider_id=provider_id, model=model_name,
    ))
    assert "已设置下次聊到" in str(provider.prompts[-1])
    events = [event async for event in chat.run(ChatRequest(
        message="聊部署", conversation_id=first.conversation_id,
        provider_id=provider_id, model=model_name,
    ))]
    assert "本轮请提醒用户：检查变更日志" in str(provider.prompts[-1])
    assert any(
        event.get("type") == "chunk" and event.get("text") == "\n\n提醒：检查变更日志"
        for event in events
    )
    assert events[-1]["response"] == "收到\n\n提醒：检查变更日志"
    with factory() as db:
        intent = db.scalars(select(StandingIntent)).one()
        assert intent.fire_count == 1


async def test_due_qq_reminder_is_sent_to_verified_owner():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="private", channel="qq", identity_id=identity.id,
            external_user_id="12345", external_conversation_type="private",
            channel_config_id="configured-account",
        )
        source = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="明天提醒我提交周报",
        )
        StandingIntentService().record(db, conversation, source, source.content)
        intent = db.scalars(select(StandingIntent)).one()
        intent.due_at = utcnow()
        db.commit()
        intent_id = intent.id

    adapter = SimpleNamespace(
        channel_config_id="configured-account", owner_user_id="12345",
        send=AsyncMock(return_value=SimpleNamespace(status="sent")),
    )
    host = RuntimeHost.__new__(RuntimeHost)
    host.chat_service = SimpleNamespace(session_factory=factory)
    host.channel_manager = SimpleNamespace(_adapters={"configured-account": adapter})
    await host._deliver_due_reminders()
    adapter.send.assert_awaited_once()
    assert adapter.send.call_args.args[0].conversation_id == "12345"
    with factory() as db:
        delivered = db.get(StandingIntent, intent_id)
        assert delivered.fire_count == 1
        assert delivered.status == "completed"
        assert StandingIntentService().due_qq(db) == []


async def test_due_local_reminder_is_persisted_in_source_conversation():
    factory = _database()
    with factory() as db:
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="local", channel="local", identity_id=identity.id
        )
        source = MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content="明天提醒我提交周报"
        )
        StandingIntentService().record(db, conversation, source, source.content)
        intent = db.scalars(select(StandingIntent)).one()
        intent.due_at = utcnow()
        db.commit()
        conversation_id = conversation.id
        identity_id = identity.id

    host = RuntimeHost.__new__(RuntimeHost)
    host.chat_service = SimpleNamespace(session_factory=factory)
    host.channel_manager = SimpleNamespace(_adapters={})
    await host._deliver_due_reminders()
    with factory() as db:
        messages = MessageRepository().list_by_conversation(db, conversation_id)
        assert messages[-1].content == "提醒：提交周报"
        intent = db.scalars(select(StandingIntent)).one()
        assert intent.fire_count == 1
        assert intent.status == "completed"
        assert StandingIntentService().due_local(db) == []
        assert StandingIntentService.recent_local(db, identity_id) == [{
            "id": intent.id,
            "content": "提交周报",
            "conversation_id": conversation_id,
            "fired_at": intent.last_fired_at.isoformat(),
        }]
