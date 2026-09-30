"""QQ OneBot v11 反向 WebSocket 适配器（MVP 仅私聊）。"""

import asyncio
import json
import hmac
import logging
from http import HTTPStatus
from urllib.parse import urlsplit
from collections.abc import Callable

from websockets.asyncio.server import serve

from ..base import ChannelAdapter, IncomingMessage


logger = logging.getLogger(__name__)


class QQAdapter(ChannelAdapter):
    name = "qq"

    def __init__(
        self,
        router,
        ws_url: str,
        access_token: str | None = None,
        on_status: Callable[[str, str | None, int], None] | None = None,
    ):
        self.router = router
        self.ws_url = ws_url
        self.access_token = access_token
        self.on_status = on_status
        self._ws = None
        self._server = None
        endpoint = urlsplit(ws_url)
        if (endpoint.scheme != "ws" or not endpoint.hostname or not endpoint.port
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("监听地址须为 ws://主机:端口/路径")
        self._host = endpoint.hostname
        self._port = endpoint.port
        self._path = endpoint.path or "/"

    def _status(self, status: str, error: str | None = None, retries: int = 0) -> None:
        if self.on_status:
            self.on_status(status, error, retries)

    async def start(self) -> None:
        self._status("connecting")
        try:
            self._server = await serve(
                self._handle_connection, self._host, self._port,
                process_request=self._authenticate,
            )
        except OSError as exc:
            self._status("error", str(exc))
            raise ValueError(f"无法监听 QQ WebSocket 地址：{exc}") from exc
        self._status("listening")

    def _authenticate(self, connection, request):
        if request.path != self._path:
            return connection.respond(HTTPStatus.NOT_FOUND, "Unknown WebSocket path")
        if self.access_token and not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(),
            f"Bearer {self.access_token}".encode(),
        ):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Invalid access token")
        if self._ws is not None:
            return connection.respond(HTTPStatus.CONFLICT, "QQ is already connected")

    async def _handle_connection(self, ws) -> None:
        # One configured QQ account owns the connection until it disconnects.
        if self._ws is not None:
            await ws.close(code=1008, reason="QQ is already connected")
            return
        self._ws = ws
        self._status("connected")
        queue = asyncio.Queue(maxsize=64)

        async def receive():
            async for raw in ws:
                await queue.put(raw)

        async def process():
            while True:
                raw = await queue.get()
                try:
                    await self._handle_raw(raw)
                except Exception:
                    logger.exception("QQ message processing failed")
                    self._status("connected", "消息处理失败，请检查模型配置或后端日志")

        tasks = [asyncio.create_task(receive()), asyncio.create_task(process()),
                 asyncio.create_task(ws.wait_closed())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._ws = None
            if self._server is not None:
                self._status("listening")

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        self._status("disconnected")

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        if data.get("post_type") != "message" or data.get("message_type") != "private":
            return
        user_id = str(data.get("user_id", ""))
        text = self._extract_text(data.get("message"))
        if not user_id or not text:
            return
        message = IncomingMessage(
            channel="qq",
            external_user_id=user_id,
            external_conversation_id=user_id,
            text=text,
            metadata={"message_type": "private"},
        )
        reply = await self.router.handle(message)
        await self.send_message(user_id, reply)

    async def send_message(self, target: str, message: str) -> None:
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": int(target), "message": [{"type": "text", "data": {"text": message}}]},
        }
        if self._ws is None:
            raise ConnectionError("NapCat 尚未连接")
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _extract_text(message) -> str:
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            parts = []
            for seg in message:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    parts.append(seg.get("data", {}).get("text", ""))
            return "".join(parts)
        return ""
