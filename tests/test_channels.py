"""Channels 测试：IncomingMessage + Conversation 外部映射。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock

from zhiyu.application.channels import ChannelService
from zhiyu.application.inbound import ChannelReliabilityService
from zhiyu.channels.base import IncomingMessage
from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.messages import (
    AudioPart,
    FilePart,
    ImagePart,
    InboundEvent,
    MentionPart,
    OutboundMessage,
    QuotePart,
    TextPart,
)
from zhiyu.infrastructure.database import models  # noqa: F401  注册 ORM 模型
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_incoming_message():
    m = IncomingMessage(channel="qq", external_user_id="123", external_conversation_id="123", text="你好")
    assert m.channel == "qq"
    assert m.text == "你好"
    assert m.metadata == {}


def test_incoming_message_converts_to_event():
    message = IncomingMessage(
        channel="qq",
        external_user_id="123",
        external_conversation_id="456",
        text="你好",
        metadata={"message_type": "group", "message_id": "m1"},
    )

    event = message.to_event()

    assert event.account_id == "qq-default"
    assert event.conversation_type == "group"
    assert event.sender_id == "123"
    assert event.conversation_id == "456"
    assert event.message_id == "m1"
    assert event.text == "你好"


def test_message_components_round_trip_and_plain_text_fallback():
    event = InboundEvent(
        channel="qq",
        account_id="qq-onebot-default",
        conversation_id="123",
        conversation_type="private",
        sender_id="123",
        parts=[
            TextPart(text="看这里"),
            ImagePart(source="managed://image/1", mime_type="image/png"),
            AudioPart(source="managed://audio/1"),
            FilePart(source="managed://file/1", name="报告.pdf"),
            MentionPart(target_id="456", display_name="小明"),
            QuotePart(message_id="old-message"),
        ],
    )

    restored = InboundEvent.model_validate_json(event.model_dump_json())
    outbound = OutboundMessage(conversation_id="123", parts=restored.parts)

    assert [part.type for part in restored.parts] == [
        "text", "image", "audio", "file", "mention", "quote"
    ]
    assert outbound.plain_text() == "看这里[图片][语音][文件: 报告.pdf]@小明[引用消息]"
    assert "managed://" not in outbound.plain_text()


def test_get_by_external():
    db = _session()
    repo = ConversationRepository()
    repo.create(db, title="c1", channel="local")
    qq = repo.create(db, title="qq chat", channel="qq", external_user_id="123")
    assert repo.get_by_external(db, "qq", "123").id == qq.id
    assert repo.get_by_external(db, "qq", "999") is None
    assert repo.get_by_external(db, "local", "123") is None
    db.close()


def test_configure_qq_can_clear_existing_token():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    class Secrets:
        def __init__(self):
            self.deleted = []

        def set(self, _reference, _value):
            pass

        def delete(self, reference):
            self.deleted.append(reference)

    secrets = Secrets()
    service = ChannelService(session_factory=session_factory, secrets=secrets)
    service.configure_qq(
        "ws://127.0.0.1:6199/ws", token="secret", owner_user_id="123"
    )
    with session_factory() as db:
        old_ref = service.configs.get(db, "qq").secret_ref

    service.configure_qq("ws://127.0.0.1:6199/ws", clear_token=True)

    with session_factory() as db:
        config = service.configs.get(db, "qq")
        assert config.secret_ref is None
        assert config.owner_user_id == "123"
    assert secrets.deleted == [old_ref]


async def test_started_qq_uses_application_group_policy(unused_tcp_port):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    manager = ChannelManager(AsyncMock(), sessions)
    service = ChannelService(sessions, manager)
    service.configure_qq(
        f"ws://127.0.0.1:{unused_tcp_port}/ws", owner_user_id="123"
    )
    config_id = service.configured_qq()["id"]
    service.set_group_policy("456", enabled=True, require_mention=True, tool_allowlist=["datetime"])

    await service.start_qq()
    try:
        adapter = manager._adapters[config_id]
        event = InboundEvent(
            channel="qq", account_id="qq-onebot-default", channel_config_id=config_id,
            conversation_id="456", conversation_type="group", sender_id="123",
            mentioned_agent=True, parts=[TextPart(text="你好")],
        )
        assert adapter._is_allowed(event) is True
        assert event.allowed_tools == ["datetime"]
        event.mentioned_agent = False
        assert adapter._is_allowed(event) is False
        event.sender_id = "other"
        event.mentioned_agent = True
        assert adapter._is_allowed(event) is False
    finally:
        await service.stop()


def test_failed_delivery_can_be_queued_and_unknown_requires_confirmation():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    reliability = ChannelReliabilityService(sessions)
    inbound = InboundEvent(
        event_id="event-1",
        channel="qq",
        account_id="qq-onebot-default",
        conversation_id="123",
        conversation_type="private",
        sender_id="123",
        parts=[TextPart(text="hi")],
    )
    assert reliability.claim(inbound)
    outbound = OutboundMessage.text("123", "ok", source_event_id=inbound.event_id)
    reliability.responded(inbound.event_id, outbound)
    failed = reliability.create_delivery(inbound.event_id, "request-1", message=outbound)
    reliability.finish_delivery(failed.id, status="failed", error="rejected")
    reliability.complete(inbound.event_id)

    queued_id = reliability.queue_delivery_retry(failed.id)
    items = reliability.list_deliveries()
    queued = next(item for item in items if item["id"] == queued_id)
    assert queued["status"] == "queued"
    assert queued["retry_of_id"] == failed.id

    unknown = reliability.create_delivery(inbound.event_id, "request-2", message=outbound)
    reliability.finish_delivery(unknown.id, status="unknown")
    try:
        reliability.queue_delivery_retry(unknown.id)
    except ValueError as exc:
        assert "显式确认" in str(exc)
    else:
        raise AssertionError("unknown delivery must require confirmation")
