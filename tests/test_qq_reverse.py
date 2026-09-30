"""Exercise the reverse listener over real local WebSocket connections."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from functools import partial

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus

from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.qq.adapter import QQAdapter


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
    adapter = QQAdapter(router, f"ws://127.0.0.1:{unused_tcp_port}/ws", "secret",
                        lambda status, error, retries: states.append(status))
    await adapter.start()
    yield adapter, router, states
    await adapter.stop()


def private_message(text="你好"):
    return json.dumps({"post_type": "message", "message_type": "private", "user_id": 123,
                       "message": [{"type": "text", "data": {"text": text}}]})


async def test_reverse_private_message_and_reconnect(listener):
    adapter, router, states = listener
    assert states[-1] == "listening"
    for _ in range(2):
        async with connect(adapter.ws_url, additional_headers={"Authorization": "Bearer secret"}) as ws:
            await ws.send('[]')
            await ws.send('not json')
            await ws.send(private_message())
            reply = json.loads(await asyncio.wait_for(ws.recv(), 2))
            assert reply == {"action": "send_private_msg", "params": {"user_id": 123,
                "message": [{"type": "text", "data": {"text": "你好 [CQ:at,qq=123]"}}]}}
            assert states[-1] == "connected"
        await wait_status(states, "listening")
    assert router.handle.await_count == 2
    assert router.handle.call_args.args[0].external_conversation_id == "123"


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
        assert states[-1] == "connected"


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
