"""渠道事件幂等与投递状态仓储。"""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ChannelDelivery, ChannelEvent, utcnow


class ChannelEventRepository:
    def claim(
        self,
        db: Session,
        *,
        event_id: str,
        channel: str,
        account_id: str,
        external_event_id: str,
        conversation_key: str,
        payload_json: str,
    ) -> ChannelEvent | None:
        event = ChannelEvent(
            id=event_id,
            channel=channel,
            account_id=account_id,
            external_event_id=external_event_id,
            conversation_key=conversation_key,
            payload_json=payload_json,
            status="processing",
            attempts=1,
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        db.refresh(event)
        return event

    def get_by_external(
        self,
        db: Session,
        channel: str,
        account_id: str,
        external_event_id: str,
    ) -> ChannelEvent | None:
        return db.scalars(
            select(ChannelEvent).where(
                ChannelEvent.channel == channel,
                ChannelEvent.account_id == account_id,
                ChannelEvent.external_event_id == external_event_id,
            )
        ).first()

    def finish(
        self,
        db: Session,
        event_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        event = db.get(ChannelEvent, event_id)
        if event is None:
            return
        event.status = status
        event.last_error = error
        event.completed_at = utcnow()
        db.commit()


class ChannelDeliveryRepository:
    def create(
        self,
        db: Session,
        *,
        event_id: str | None,
        request_id: str,
    ) -> ChannelDelivery:
        delivery = ChannelDelivery(
            id=str(uuid4()),
            event_id=event_id,
            request_id=request_id,
            status="pending",
            attempts=1,
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery

    def finish(
        self,
        db: Session,
        delivery_id: str,
        *,
        status: str,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        delivery = db.get(ChannelDelivery, delivery_id)
        if delivery is None:
            return
        delivery.status = status
        delivery.provider_message_id = provider_message_id
        delivery.last_error = error
        delivery.completed_at = utcnow()
        db.commit()
