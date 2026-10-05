"""渠道事件与投递状态的短事务应用服务。"""

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from zhiyu.channels.messages import InboundEvent
from zhiyu.infrastructure.database.db import SessionLocal
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
            )
        return claimed is not None

    def complete(self, event_id: str) -> None:
        with self.session_factory() as db:
            self.events.finish(db, event_id, "completed")

    def fail(self, event_id: str, error: str) -> None:
        with self.session_factory() as db:
            self.events.finish(db, event_id, "failed", error)

    def create_delivery(
        self,
        event_id: str | None,
        request_id: str,
    ) -> PendingDelivery:
        with self.session_factory() as db:
            delivery = self.deliveries.create(
                db,
                event_id=event_id,
                request_id=request_id,
            )
            return PendingDelivery(delivery.id, delivery.request_id)

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
