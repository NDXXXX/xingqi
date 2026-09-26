"""QQ OneBot v11 反向 WebSocket 适配器（MVP 仅私聊）。"""

import asyncio
import json

import websockets

from ..base import ChannelAdapter, IncomingMessage


class QQAdapter(ChannelAdapter):
    name = "qq"

    def __init__(self, router, ws_url: str, access_token: str | None = None):
        self.router = router
        self.ws_url = ws_url
        self.access_token = access_token
        self._ws = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                headers = {}
                if self.access_token:
                    headers["Authorization"] = f"Bearer {self.access_token}"
                async with websockets.connect(self.ws_url, additional_headers=headers) as ws:
                    self._ws = ws
                    async for raw in ws:
                        await self._handle_raw(raw)
            except Exception:
                if not self._running:
                    break
                await asyncio.sleep(5)

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
