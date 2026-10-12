"""渠道事件与投递状态的短事务应用服务。"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import select

from zhiyu.channels.messages import InboundEvent, OutboundMessage
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import Message
from zhiyu.infrastructure.database.repositories.channel_repository import (
    ChannelDeliveryRepository,
    ChannelEventRepository,
)


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    id: str
    request_id: str


class ChannelReliabilityService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
    ) -> None:
        self.session_factory = session_factory
        self.events = ChannelEventRepository()
        self.deliveries = ChannelDeliveryRepository()
        self.worker_id = str(uuid4())

    def claim(self, event: InboundEvent) -> bool:
        external_event_id = event.message_id or event.event_id
        conversation_key = ":".join(
            (
                event.channel,
                event.account_id,
                event.conversation_type,
                event.conversation_id,
            )
        )
        with self.session_factory() as db:
            claimed = self.events.claim(
                db,
                event_id=event.event_id,
                channel=event.channel,
                account_id=event.account_id,
                external_event_id=external_event_id,
                conversation_key=conversation_key,
                payload_json=event.model_dump_json(),
                channel_config_id=event.channel_config_id,
                lease_owner=self.worker_id,
            )
        return claimed is not None

    def complete(self, event_id: str) -> None:
        with self.session_factory() as db:
            self.events.finish(db, event_id, "completed")

    def fail(self, event_id: str, error: str) -> None:
        with self.session_factory() as db:
            self.events.finish(db, event_id, "failed", error)

    def retry_or_fail(
        self, event_id: str, error: str, *, retryable: bool = True
    ) -> None:
        with self.session_factory() as db:
            self.events.retry_or_fail(db, event_id, error, retryable=retryable)

    def responded(
        self,
        event_id: str,
        message: OutboundMessage,
        *,
        response_message_id: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            if response_message_id is None:
                response_message_id = db.scalar(
                    select(Message.id)
                    .where(
                        Message.source_event_id == event_id,
                        Message.role == "assistant",
                    )
                    .order_by(Message.created_at.desc())
                )
            self.events.mark_responded(
                db,
                event_id,
                response_message_id=response_message_id,
                outbound_message_json=message.model_dump_json(),
            )

    def recoverable(self, channel_config_id: str, limit: int = 20) -> list[tuple[str, str, str]]:
        with self.session_factory() as db:
            rows = self.events.list_recoverable(
                db, channel_config_id=channel_config_id, limit=limit
            )
            return [(item.id, item.status, item.payload_json) for item in rows]

    def reclaim(self, event_id: str) -> bool:
        with self.session_factory() as db:
            return self.events.reclaim(
                db, event_id, lease_owner=self.worker_id
            ) is not None

    def outbound_for(self, event_id: str) -> OutboundMessage | None:
        with self.session_factory() as db:
            event = self.events.get(db, event_id)
            if event is None or not event.outbound_message_json:
                return None
            return OutboundMessage.model_validate_json(event.outbound_message_json)

    def queued_outbound_for(self, event_id: str) -> OutboundMessage | None:
        with self.session_factory() as db:
            delivery = self.deliveries.queued_for_event(db, event_id)
            if delivery is None or not delivery.message_json:
                return None
            return OutboundMessage.model_validate_json(delivery.message_json)

    def event_status(self, event_id: str) -> str | None:
        with self.session_factory() as db:
            event = self.events.get(db, event_id)
            return event.status if event else None

    def update_payload(self, event: InboundEvent) -> None:
        with self.session_factory() as db:
            stored = self.events.get(db, event.event_id)
            if stored is None:
                return
            stored.payload_json = event.model_dump_json()
            db.commit()

    def close_interrupted_delivery(self, event_id: str) -> bool:
        """把进程崩溃时遗留的 pending 投递保守标记为 unknown。"""
        with self.session_factory() as db:
            delivery = self.deliveries.pending_for_event(db, event_id)
            if delivery is None:
                return False
            self.deliveries.finish(
                db,
                delivery.id,
                status="unknown",
                error="进程在等待 OneBot 回执时中断",
            )
            self.events.finish(db, event_id, "completed")
            return True

    def create_delivery(
        self,
        event_id: str | None,
        request_id: str,
        *,
        channel_config_id: str | None = None,
        message: OutboundMessage | None = None,
        retry_of_id: str | None = None,
    ) -> PendingDelivery:
        with self.session_factory() as db:
            if event_id:
                queued = self.deliveries.claim_queued(db, event_id)
                if queued is not None:
                    return PendingDelivery(queued.id, queued.request_id)
            delivery = self.deliveries.create(
                db,
                event_id=event_id,
                request_id=request_id,
                channel_config_id=channel_config_id,
                message_json=message.model_dump_json() if message else None,
                retry_of_id=retry_of_id,
            )
            return PendingDelivery(delivery.id, delivery.request_id)

    def list_deliveries(self, limit: int = 50) -> list[dict]:
        with self.session_factory() as db:
            return [
                {
                    "id": item.id,
                    "event_id": item.event_id,
                    "status": item.status,
                    "attempts": item.attempts,
                    "provider_message_id": item.provider_message_id,
                    "last_error": item.last_error,
                    "retry_of_id": item.retry_of_id,
                    "created_at": item.created_at,
                }
                for item in self.deliveries.list_recent(db, limit)
            ]

    def queue_delivery_retry(self, delivery_id: str, *, allow_unknown: bool = False) -> str:
        with self.session_factory() as db:
            delivery = self.deliveries.get(db, delivery_id)
            if delivery is None:
                raise ValueError("投递记录不存在")
            return self.deliveries.queue_retry(
                db, delivery, allow_unknown=allow_unknown
            ).id

    def finish_delivery(
        self,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            self.deliveries.finish(
                db,
                delivery_id,
                status=status,
                provider_message_id=provider_message_id,
                error=error,
            )
