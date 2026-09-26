"""QQ OneBot v11 反向 WebSocket 适配器（MVP 仅私聊）。"""

import asyncio
import json
import random
from collections.abc import Callable

import websockets

from ..base import ChannelAdapter, IncomingMessage


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
        self._running = False

    def _status(self, status: str, error: str | None = None, retries: int = 0) -> None:
        if self.on_status:
            self.on_status(status, error, retries)

    async def start(self) -> None:
        self._running = True
        retries = 0
        delays = (1, 2, 5, 10, 30)
        while self._running:
            try:
                self._status("connecting" if retries == 0 else "reconnecting", None, retries)
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                    self._ws = ws
                    retries = 0
                    self._status("connected")
                    async for raw in ws:
                        await self._handle_raw(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._running:
                    break
                retries += 1
                self._status("reconnecting", str(exc), retries)
                base_delay = delays[min(retries - 1, len(delays) - 1)]
                await asyncio.sleep(base_delay + random.uniform(0, min(1.0, base_delay * 0.2)))
            finally:
                self._ws = None
        self._status("disconnected", None, retries)

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()

    async def _handle_raw(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
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
            "params": {"user_id": int(target), "message": message},
        }
        if self._ws is not None:
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
