"""QQ OneBot v11 反向 WebSocket 适配器。"""

import asyncio
import json
import hmac
import ipaddress
import logging
from http import HTTPStatus
from urllib.parse import urlsplit
from collections.abc import Callable
from uuid import uuid4

from websockets.asyncio.server import serve

from ..base import ChannelAdapter
from ..messages import DeliveryReceipt, InboundEvent, OutboundMessage, TextPart
from ..pipeline import (
    AgentStage,
    CommandStage,
    DedupStage,
    DeliveryStage,
    InboundPipeline,
    PolicyStage,
    RenderStage,
    SessionStage,
)


logger = logging.getLogger(__name__)
SEND_TIMEOUT_SECONDS = 5


class QQAdapter(ChannelAdapter):
    name = "qq"

    def __init__(
        self,
        router,
        ws_url: str,
        access_token: str | None = None,
        on_status: Callable[[str, str | None, int], None] | None = None,
        owner_user_id: str | None = None,
        account_id: str = "qq-onebot-default",
        allow_group_messages: bool = False,
        group_require_mention: bool = True,
        reliability=None,
        send_timeout_seconds: float = SEND_TIMEOUT_SECONDS,
        max_concurrency: int = 4,
    ):
        self.router = router
        self.ws_url = ws_url
        self.access_token = access_token
        self.owner_user_id = owner_user_id
        self.account_id = account_id
        self.allow_group_messages = allow_group_messages
        self.group_require_mention = group_require_mention
        self.reliability = reliability
        self.send_timeout_seconds = send_timeout_seconds
        self.on_status = on_status
        self._ws = None
        self._server = None
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}
        self._message_slots = asyncio.Semaphore(max_concurrency)
        self._claimed_event_ids: set[str] = set()
        endpoint = urlsplit(ws_url)
        if (endpoint.scheme != "ws" or not endpoint.hostname or not endpoint.port
                or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
            raise ValueError("监听地址须为 ws://主机:端口/路径")
        self._host = endpoint.hostname
        self._port = endpoint.port
        self._path = endpoint.path or "/"
        if not access_token and not self._is_loopback_host(self._host):
            raise ValueError("非本机 QQ WebSocket 监听地址必须配置 Access Token")
        self._pipeline = InboundPipeline(
            [
                PolicyStage(self._is_allowed),
                DedupStage(self._is_duplicate),
                SessionStage(),
                CommandStage({"/new": self._new_session}),
                AgentStage(self.router.handle),
                RenderStage(),
                DeliveryStage(self.send),
            ]
        )

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
        inflight: set[asyncio.Task] = set()

        async def receive():
            async for raw in ws:
                data = self._decode(raw)
                if data is None:
                    continue
                echo = data.get("echo")
                pending = self._pending_requests.get(str(echo)) if echo is not None else None
                if pending is not None and not pending.done():
                    pending.set_result(data)
                    continue
                await queue.put(data)

        async def run_one(data: dict) -> None:
            try:
                await self._handle_data(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("QQ message processing failed")
                self._status("connected", "消息处理失败，请检查模型配置或后端日志")
            finally:
                self._message_slots.release()

        async def process():
            while True:
                data = await queue.get()
                await self._message_slots.acquire()
                task = asyncio.create_task(run_one(data))
                inflight.add(task)
                task.add_done_callback(inflight.discard)

        tasks = [asyncio.create_task(receive()), asyncio.create_task(process()),
                 asyncio.create_task(ws.wait_closed())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            for task in inflight:
                task.cancel()
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("NapCat 连接已断开"))
            await asyncio.gather(*tasks, return_exceptions=True)
            if inflight:
                await asyncio.gather(*inflight, return_exceptions=True)
            self._pending_requests.clear()
            self._conversation_locks.clear()
            self._ws = None
            if self._server is not None:
                self._status("listening")

    async def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        self._status("disconnected")

    async def _handle_data(self, data: dict) -> None:
        event = self._to_event(data)
        if event is None:
            return
        lock_key = ":".join(
            (event.account_id, event.conversation_type, event.conversation_id)
        )
        lock = self._conversation_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            try:
                result = await self._pipeline.execute(event)
            except Exception as exc:
                if self.reliability is not None and event.event_id in self._claimed_event_ids:
                    self.reliability.fail(event.event_id, str(exc))
                raise
            else:
                if (
                    self.reliability is not None
                    and result.data.get("dedup_checked")
                    and not result.data.get("duplicate")
                ):
                    self.reliability.complete(event.event_id)
            finally:
                self._claimed_event_ids.discard(event.event_id)

    def _to_event(self, data: dict) -> InboundEvent | None:
        if data.get("post_type") != "message":
            return None
        message_type = data.get("message_type")
        if message_type not in {"private", "group"}:
            return None
        user_id = str(data.get("user_id", ""))
        text = self._extract_text(data.get("message"))
        if not user_id or not text:
            return None
        if message_type == "group":
            conversation_id = str(data.get("group_id", ""))
            if not conversation_id:
                return None
        else:
            conversation_id = user_id
        message_id = data.get("message_id")
        event_id = (
            f"qq:{self.account_id}:{message_id}"
            if message_id is not None
            else None
        )
        event_data = {"event_id": event_id} if event_id is not None else {}
        event = InboundEvent(
            **event_data,
            channel="qq",
            account_id=self.account_id,
            conversation_id=conversation_id,
            conversation_type=message_type,
            sender_id=user_id,
            sender_name=(data.get("sender") or {}).get("nickname"),
            message_id=str(message_id) if message_id is not None else None,
            mentioned_agent=self._mentioned_agent(data),
            parts=[TextPart(text=text)],
            raw=data,
        )
        return event

    async def send(self, message: OutboundMessage) -> DeliveryReceipt:
        if self._ws is None:
            raise ConnectionError("NapCat 尚未连接")
        request_id = str(uuid4())
        action = "send_group_msg" if message.conversation_type == "group" else "send_private_msg"
        target_key = "group_id" if message.conversation_type == "group" else "user_id"
        payload = {
            "action": action,
            "params": {
                target_key: int(message.conversation_id),
                "message": [{"type": "text", "data": {"text": message.plain_text()}}],
            },
            "echo": request_id,
        }
        pending_delivery = None
        if self.reliability is not None:
            pending_delivery = self.reliability.create_delivery(
                message.source_event_id,
                request_id,
            )
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future
        try:
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
            response = await asyncio.wait_for(
                future,
                timeout=self.send_timeout_seconds,
            )
        except TimeoutError:
            receipt = DeliveryReceipt(
                delivery_id=pending_delivery.id if pending_delivery else str(uuid4()),
                status="unknown",
                error="OneBot 发送响应超时",
            )
        except Exception as exc:
            receipt = DeliveryReceipt(
                delivery_id=pending_delivery.id if pending_delivery else str(uuid4()),
                status="unknown",
                error=str(exc),
            )
        else:
            ok = response.get("status") == "ok" and response.get("retcode", 0) == 0
            response_data = response.get("data") or {}
            provider_message_id = response_data.get("message_id")
            receipt = DeliveryReceipt(
                delivery_id=pending_delivery.id if pending_delivery else str(uuid4()),
                status="sent" if ok else "failed",
                provider_message_id=(
                    str(provider_message_id) if provider_message_id is not None else None
                ),
                error=None if ok else str(response.get("message") or "OneBot 发送失败"),
            )
        finally:
            self._pending_requests.pop(request_id, None)
        if self.reliability is not None and pending_delivery is not None:
            self.reliability.finish_delivery(
                pending_delivery.id,
                status=receipt.status,
                provider_message_id=receipt.provider_message_id,
                error=receipt.error,
            )
        return receipt

    def _is_allowed(self, event: InboundEvent) -> bool:
        if not self.owner_user_id or event.sender_id != self.owner_user_id:
            return False
        if event.conversation_type == "private":
            return True
        return self.allow_group_messages and (
            not self.group_require_mention or event.mentioned_agent
        )

    async def _new_session(self, event: InboundEvent) -> str:
        if event.conversation_type != "private":
            return "群聊暂不支持手动新建会话。"
        return await self.router.new_session(event)

    def _is_duplicate(self, event: InboundEvent) -> bool:
        if self.reliability is None:
            return False
        claimed = self.reliability.claim(event)
        if claimed:
            self._claimed_event_ids.add(event.event_id)
        return not claimed

    @staticmethod
    def _decode(raw: str) -> dict | None:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _mentioned_agent(data: dict) -> bool:
        self_id = str(data.get("self_id", ""))
        message = data.get("message")
        if not self_id or not isinstance(message, list):
            return False
        return any(
            isinstance(segment, dict)
            and segment.get("type") == "at"
            and str((segment.get("data") or {}).get("qq", "")) == self_id
            for segment in message
        )

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

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        if host.lower() == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
