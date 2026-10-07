"""Exercise the reverse listener over real local WebSocket connections."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from functools import partial

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.inbound import ChannelReliabilityService
from zhiyu.application.channels import ChannelService
from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.messages import (
    AudioPart,
    DeliveryReceipt,
    FilePart,
    ImagePart,
    MentionPart,
    OutboundMessage,
    QuotePart,
    TextPart,
)
from zhiyu.channels.pipeline import AgentStage, DeliveryStage, InboundPipeline, RenderStage
from zhiyu.channels.qq.adapter import QQAdapter
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import ChannelDelivery, ChannelEvent
from zhiyu.infrastructure.database.models import utcnow
from zhiyu.infrastructure.database.repositories.channel_repository import (
    ChannelGroupPolicyRepository,
)
from zhiyu.infrastructure.database.repositories.integration_repository import (
    ChannelConfigRepository,
)


connect = partial(ws_connect, proxy=None)


async def wait_status(states, expected):
    async with asyncio.timeout(2):
        while states[-1] != expected:
            await asyncio.sleep(0.01)


@pytest.fixture
async def listener(unused_tcp_port):
    states = []
    router = AsyncMock()
    router.handle.return_value = "你好 [CQ:at,qq=123]"
    adapter = QQAdapter(
        router,
        f"ws://127.0.0.1:{unused_tcp_port}/ws",
        "secret",
        lambda status, error, retries: states.append(status),
        owner_user_id="123",
    )
    await adapter.start()
    yield adapter, router, states
    await adapter.stop()


def private_message(text="你好", user_id=123, message_id=None):
    payload = {
        "post_type": "message",
        "message_type": "private",
        "user_id": user_id,
        "message": [{"type": "text", "data": {"text": text}}],
    }
    if message_id is not None:
        payload["message_id"] = message_id
    return json.dumps(payload)


def group_message(text="你好", group_id=456, *, mentioned=True, message_id=1):
    message = []
    if mentioned:
        message.append({"type": "at", "data": {"qq": "999"}})
    message.append({"type": "text", "data": {"text": text}})
    return {
        "post_type": "message",
        "message_type": "group",
        "self_id": 999,
        "user_id": 123,
        "group_id": group_id,
        "message_id": message_id,
        "message": message,
    }


async def test_reverse_private_message_and_reconnect(listener):
    adapter, router, states = listener
    assert states[-1] == "listening"
    for _ in range(2):
        async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
            await ws.send('[]')
            await ws.send('not json')
            await ws.send(private_message())
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert reply["action"] == "send_private_msg"
            assert reply["params"] == {
                "user_id": 123,
                "message": [
                    {"type": "text", "data": {"text": "你好 [CQ:at,qq=123]"}}
                ],
            }
            assert reply["echo"]
            await ws.send(json.dumps({
                "status": "ok",
                "retcode": 0,
                "data": {"message_id": 789},
                "echo": reply["echo"],
            }))
            assert states[-1] == "connected"
        await wait_status(states, "listening")
    assert router.handle.await_count == 2
    assert router.handle.call_args.args[0].external_conversation_id == "123"


async def test_rejected_account_does_not_block_correct_reconnect(listener):
    adapter, _, states = listener
    headers = {"Authorization": "Bearer secret", "X-Self-ID": "123"}
    async with connect(adapter.ws_url, additional_headers=headers):
        pass
    await wait_status(states, "listening")

    async with connect(adapter.ws_url, additional_headers={
        "Authorization": "Bearer secret", "X-Self-ID": "456",
    }) as rejected:
        await rejected.wait_closed()
        assert rejected.close_code == 1008

    async with connect(adapter.ws_url, additional_headers=headers):
        await wait_status(states, "connected")


@pytest.mark.parametrize("path,token,status", [("/ws", "bad", 401), ("/wrong", "secret", 404)])
async def test_handshake_rejected(listener, path, token, status):
    adapter, router, states = listener
    with pytest.raises(InvalidStatus) as exc:
        async with connect(adapter.ws_url.removesuffix('/ws') + path,
                           additional_headers={"Authorization": f"Bearer {token}"}):
            pass
    assert exc.value.response.status_code == status
    assert states[-1] == "listening"
    router.handle.assert_not_called()


async def test_second_client_rejected(listener):
    adapter, _, states = listener
    headers = {"Authorization": "Bearer secret"}
    async with connect(adapter.ws_url, additional_headers=headers):
        with pytest.raises(InvalidStatus) as exc:
            async with connect(adapter.ws_url, additional_headers=headers):
                pass
        assert exc.value.response.status_code == 409
        assert states[-1] == "connected"


async def test_agent_error_does_not_disconnect(listener):
    adapter, router, states = listener
    router.handle.side_effect = [RuntimeError("model unavailable"), "recovered"]
    async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
        await ws.send(private_message())
        await ws.send(private_message("再试一次"))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
        assert reply["params"]["message"][0]["data"]["text"] == "recovered"
        await ws.send(json.dumps({
            "status": "ok", "retcode": 0, "data": {}, "echo": reply["echo"]
        }))
        assert states[-1] == "connected"


async def test_new_command_starts_session_without_calling_agent(listener):
    adapter, router, _ = listener
    router.new_session.return_value = "已开启新的对话。"
    async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
        await ws.send(private_message("/new"))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
        await ws.send(json.dumps({
            "status": "ok", "retcode": 0, "data": {}, "echo": reply["echo"]
        }))
    assert reply["params"]["message"][0]["data"]["text"] == "已开启新的对话。"
    router.new_session.assert_awaited_once()
    router.handle.assert_not_called()


async def test_non_owner_private_message_is_ignored(listener):
    adapter, router, _ = listener
    async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
        await ws.send(private_message("not for the owner", user_id=456))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(ws.recv(), 0.05)
    router.handle.assert_not_called()
    router.new_session.assert_not_called()


async def test_stop_cancels_busy_agent_and_releases_port(listener):
    adapter, router, states = listener
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(message):
        entered.set()
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    router.handle.side_effect = slow
    async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
        await ws.send(private_message())
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.wait_for(adapter.stop(), 2)
        assert cancelled.is_set()
        assert states[-1] == "disconnected"
    await adapter.start()
    assert states[-1] == "listening"


async def test_manager_reports_bind_failure(listener):
    adapter, _, _ = listener
    manager = ChannelManager(AsyncMock())
    with pytest.raises(ValueError, match="无法监听"):
        await manager.connect("qq", adapter.ws_url)
    assert manager.list()[0]["status"] == "error"
    await manager.close_all()


@pytest.mark.parametrize("url", ["http://127.0.0.1:6199", "ws://127.0.0.1", "ws://u:p@localhost:6199", "ws://localhost:6199/ws?token=x"])
def test_invalid_listener_url(url):
    with pytest.raises(ValueError):
        QQAdapter(AsyncMock(), url)


def test_non_loopback_listener_requires_access_token():
    with pytest.raises(ValueError, match="Access Token"):
        QQAdapter(AsyncMock(), "ws://0.0.0.0:6199/ws", owner_user_id="123")


def test_loopback_listener_allows_missing_access_token():
    adapter = QQAdapter(
        AsyncMock(), "ws://127.0.0.1:6199/ws", owner_user_id="123"
    )
    assert adapter.access_token is None


def test_media_only_message_is_preserved_as_structured_parts():
    adapter = QQAdapter(AsyncMock(), "ws://127.0.0.1:6199/ws", owner_user_id="123")
    event = adapter._to_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 123,
            "message_id": 7,
            "message": [
                {"type": "image", "data": {"url": "https://example.test/a.png"}},
                {"type": "reply", "data": {"id": "6"}},
            ],
        }
    )

    assert event is not None
    assert [part.type for part in event.parts] == ["image", "quote"]
    assert event.text == ""
    assert event.plain_text() == "[图片][引用消息]"


async def test_outbound_components_render_to_onebot_segments():
    adapter = QQAdapter(AsyncMock(), "ws://127.0.0.1:6199/ws", owner_user_id="123")
    ws = AsyncMock()

    async def reply(raw):
        payload = json.loads(raw)
        asyncio.get_running_loop().call_soon(
            adapter._pending_requests[payload["echo"]].set_result,
            {"status": "ok", "retcode": 0, "data": {}, "echo": payload["echo"]},
        )

    ws.send.side_effect = reply
    adapter._ws = ws
    receipt = await adapter.send(
        OutboundMessage(
            conversation_id="123",
            parts=[
                QuotePart(message_id="old"),
                TextPart(text="看"),
                MentionPart(target_id="456"),
                ImagePart(source="https://example.test/a.png"),
                AudioPart(source="https://example.test/a.mp3"),
                FilePart(source="https://example.test/a.pdf", name="a.pdf"),
            ],
        )
    )

    payload = json.loads(ws.send.await_args.args[0])
    assert receipt.status == "sent"
    assert [item["type"] for item in payload["params"]["message"]] == [
        "reply", "text", "at", "image", "record", "file"
    ]


async def test_persistent_dedup_and_delivery_receipt(unused_tcp_port):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    router = AsyncMock()
    router.handle.return_value = "收到"
    reliability = ChannelReliabilityService(session_factory)
    adapter = QQAdapter(
        router,
        f"ws://127.0.0.1:{unused_tcp_port}/ws",
        owner_user_id="123",
        reliability=reliability,
        send_timeout_seconds=0.2,
    )
    await adapter.start()
    try:
        async with connect(adapter.ws_url) as ws:
            raw = private_message(message_id=42)
            await ws.send(raw)
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
            await ws.send(json.dumps({
                "status": "ok",
                "retcode": 0,
                "data": {"message_id": 9001},
                "echo": reply["echo"],
            }))

            async with asyncio.timeout(2):
                while True:
                    with session_factory() as db:
                        stored = db.get(ChannelEvent, "qq:qq-onebot-default:42")
                        if stored is not None and stored.status == "completed":
                            break
                    await asyncio.sleep(0.01)

            await ws.send(raw)
            await asyncio.sleep(0.05)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(ws.recv(), 0.05)

        assert router.handle.await_count == 1
        with session_factory() as db:
            events = list(db.scalars(select(ChannelEvent)))
            deliveries = list(db.scalars(select(ChannelDelivery)))
            assert len(events) == 1
            assert events[0].status == "completed"
            assert len(deliveries) == 1
            assert deliveries[0].status == "sent"
            assert deliveries[0].provider_message_id == "9001"
    finally:
        await adapter.stop()


def test_group_policy_requires_explicit_enable_and_mention():
    router = AsyncMock()
    disabled = QQAdapter(
        router,
        "ws://127.0.0.1:6199/ws",
        owner_user_id="123",
    )
    enabled = QQAdapter(
        router,
        "ws://127.0.0.1:6199/ws",
        owner_user_id="123",
        allow_group_messages=True,
    )

    mentioned = enabled._to_event(group_message(mentioned=True))
    not_mentioned = enabled._to_event(group_message(mentioned=False))

    assert mentioned is not None
    assert mentioned.conversation_type == "group"
    assert mentioned.conversation_id == "456"
    assert disabled._is_allowed(mentioned) is False
    assert enabled._is_allowed(mentioned) is True
    assert not_mentioned is not None
    assert enabled._is_allowed(not_mentioned) is False


def test_persisted_group_policy_is_required_and_sets_tool_scope():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        config = ChannelConfigRepository().upsert(
            db, "qq", "ws://127.0.0.1:6199/ws", None, owner_user_id="123"
        )
    reliability = ChannelReliabilityService(sessions)
    adapter = QQAdapter(
        AsyncMock(),
        "ws://127.0.0.1:6199/ws",
        owner_user_id="123",
        channel_config_id=config.id,
        reliability=reliability,
        group_policy=ChannelService(sessions).allow_group_event,
    )
    event = adapter._to_event(group_message())
    assert event is not None
    assert adapter._is_allowed(event) is False

    with sessions() as db:
        ChannelGroupPolicyRepository().upsert(
            db,
            config.id,
            "456",
            enabled=True,
            require_mention=True,
            tool_allowlist=["datetime"],
            system_prompt="只回答项目问题",
        )

    assert adapter._is_allowed(event) is True
    assert event.allowed_tools == ["datetime"]
    assert event.system_prompt == "只回答项目问题"


async def test_responded_event_recovers_without_running_agent(unused_tcp_port):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        config = ChannelConfigRepository().upsert(
            db, "qq", f"ws://127.0.0.1:{unused_tcp_port}/ws", None, owner_user_id="123"
        )
    reliability = ChannelReliabilityService(sessions)
    adapter = QQAdapter(
        AsyncMock(),
        config.endpoint,
        owner_user_id="123",
        channel_config_id=config.id,
        reliability=reliability,
    )
    event = adapter._to_event(json.loads(private_message(message_id=88)))
    assert event is not None and reliability.claim(event)
    outbound = OutboundMessage.text(
        "123", "已生成", source_event_id=event.event_id
    )
    reliability.responded(event.event_id, outbound)
    ws = AsyncMock()

    async def reply(raw):
        payload = json.loads(raw)
        asyncio.get_running_loop().call_soon(
            adapter._pending_requests[payload["echo"]].set_result,
            {"status": "ok", "retcode": 0, "data": {}, "echo": payload["echo"]},
        )

    ws.send.side_effect = reply
    adapter._ws = ws

    assert await adapter.recover_once() == 1
    adapter.router.handle.assert_not_called()
    with sessions() as db:
        assert db.get(ChannelEvent, event.event_id).status == "completed"


async def test_interrupted_pending_delivery_becomes_unknown_without_resend(unused_tcp_port):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        config = ChannelConfigRepository().upsert(
            db, "qq", f"ws://127.0.0.1:{unused_tcp_port}/ws", None, owner_user_id="123"
        )
    reliability = ChannelReliabilityService(sessions)
    adapter = QQAdapter(
        AsyncMock(), config.endpoint, owner_user_id="123",
        channel_config_id=config.id, reliability=reliability,
    )
    event = adapter._to_event(json.loads(private_message(message_id=89)))
    assert event is not None and reliability.claim(event)
    outbound = OutboundMessage.text("123", "已生成", source_event_id=event.event_id)
    reliability.responded(event.event_id, outbound)
    pending = reliability.create_delivery(
        event.event_id,
        "request-before-crash",
        channel_config_id=config.id,
        message=outbound,
    )
    adapter._ws = AsyncMock()

    assert await adapter.recover_once() == 1
    adapter._ws.send.assert_not_called()
    with sessions() as db:
        assert db.get(ChannelDelivery, pending.id).status == "unknown"
        assert db.get(ChannelEvent, event.event_id).status == "completed"


async def test_expired_processing_event_is_reclaimed(unused_tcp_port):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        config = ChannelConfigRepository().upsert(
            db, "qq", f"ws://127.0.0.1:{unused_tcp_port}/ws", None, owner_user_id="123"
        )
    reliability = ChannelReliabilityService(sessions)
    router = AsyncMock()
    router.handle.return_value = "恢复完成"
    adapter = QQAdapter(
        router, config.endpoint, owner_user_id="123",
        channel_config_id=config.id, reliability=reliability,
    )
    event = adapter._to_event(json.loads(private_message(message_id=90)))
    assert event is not None and reliability.claim(event)
    with sessions() as db:
        stored = db.get(ChannelEvent, event.event_id)
        stored.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    ws = AsyncMock()

    async def reply(raw):
        payload = json.loads(raw)
        asyncio.get_running_loop().call_soon(
            adapter._pending_requests[payload["echo"]].set_result,
            {"status": "ok", "retcode": 0, "data": {}, "echo": payload["echo"]},
        )

    ws.send.side_effect = reply
    adapter._ws = ws

    assert await adapter.recover_once() == 1
    router.handle.assert_awaited_once()
    with sessions() as db:
        stored = db.get(ChannelEvent, event.event_id)
        assert stored.status == "completed"
        assert stored.attempts == 2


async def test_same_conversation_is_serial_and_different_conversations_run_parallel():
    adapter = QQAdapter(
        AsyncMock(),
        "ws://127.0.0.1:6199/ws",
        owner_user_id="123",
        allow_group_messages=True,
    )
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_same_entered = asyncio.Event()
    other_entered = asyncio.Event()

    async def handle(event):
        if event.text == "first":
            first_entered.set()
            await release_first.wait()
        elif event.text == "same":
            second_same_entered.set()
        else:
            other_entered.set()
        return "ok"

    sender = AsyncMock(return_value=DeliveryReceipt(status="sent"))
    adapter._pipeline = InboundPipeline(
        [AgentStage(handle), RenderStage(), DeliveryStage(sender)]
    )

    first = asyncio.create_task(
        adapter._handle_data(group_message("first", group_id=1, message_id=1))
    )
    await asyncio.wait_for(first_entered.wait(), 1)
    same = asyncio.create_task(
        adapter._handle_data(group_message("same", group_id=1, message_id=2))
    )
    other = asyncio.create_task(
        adapter._handle_data(group_message("other", group_id=2, message_id=3))
    )

    await asyncio.wait_for(other_entered.wait(), 1)
    await asyncio.sleep(0)
    assert not second_same_entered.is_set()

    release_first.set()
    await asyncio.gather(first, same, other)
    assert second_same_entered.is_set()
