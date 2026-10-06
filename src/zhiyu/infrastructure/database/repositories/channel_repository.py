"""渠道事件、投递、群策略与媒体状态仓储。"""

from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    ChannelDelivery,
    ChannelEvent,
    ChannelGroupPolicy,
    ChannelMediaAsset,
    utcnow,
)


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
        channel_config_id: str | None = None,
        lease_owner: str | None = None,
        lease_seconds: int = 120,
    ) -> ChannelEvent | None:
        now = utcnow()
        event = ChannelEvent(
            id=event_id,
            channel=channel,
            channel_config_id=channel_config_id,
            account_id=account_id,
            external_event_id=external_event_id,
            conversation_key=conversation_key,
            payload_json=payload_json,
            status="processing",
            attempts=1,
            available_at=now,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        db.add(event)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return None
        db.refresh(event)
        return event

    def get(self, db: Session, event_id: str) -> ChannelEvent | None:
        return db.get(ChannelEvent, event_id)

    def list_recoverable(
        self,
        db: Session,
        *,
        channel_config_id: str,
        limit: int = 20,
    ) -> list[ChannelEvent]:
        now = utcnow()
        return list(
            db.scalars(
                select(ChannelEvent)
                .where(
                    ChannelEvent.channel_config_id == channel_config_id,
                    or_(
                        ChannelEvent.status == "pending",
                        ChannelEvent.status == "responded",
                        (
                            (ChannelEvent.status == "processing")
                            & (ChannelEvent.lease_expires_at <= now)
                        ),
                    ),
                    ChannelEvent.available_at <= now,
                )
                .order_by(ChannelEvent.received_at)
                .limit(limit)
            )
        )

    def reclaim(
        self,
        db: Session,
        event_id: str,
        *,
        lease_owner: str,
        lease_seconds: int = 120,
    ) -> ChannelEvent | None:
        now = utcnow()
        result = db.execute(
            update(ChannelEvent)
            .where(
                ChannelEvent.id == event_id,
                or_(
                    ChannelEvent.status == "pending",
                    (
                        (ChannelEvent.status == "processing")
                        & (ChannelEvent.lease_expires_at <= now)
                    ),
                ),
            )
            .values(
                status="processing",
                attempts=ChannelEvent.attempts + 1,
                lease_owner=lease_owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
                last_error=None,
            )
        )
        db.commit()
        if result.rowcount != 1:
            return None
        return db.get(ChannelEvent, event_id)

    def mark_responded(
        self,
        db: Session,
        event_id: str,
        *,
        response_message_id: str | None,
        outbound_message_json: str,
    ) -> None:
        event = db.get(ChannelEvent, event_id)
        if event is None:
            return
        event.status = "responded"
        event.response_message_id = response_message_id
        event.outbound_message_json = outbound_message_json
        event.lease_owner = None
        event.lease_expires_at = None
        event.updated_at = utcnow()
        db.commit()

    def retry_or_fail(
        self,
        db: Session,
        event_id: str,
        error: str,
        *,
        max_attempts: int = 3,
        retryable: bool = True,
    ) -> None:
        event = db.get(ChannelEvent, event_id)
        if event is None:
            return
        should_retry = retryable and event.attempts < max_attempts
        event.status = "pending" if should_retry else "failed"
        event.available_at = utcnow()
        event.lease_owner = None
        event.lease_expires_at = None
        event.last_error = error
        event.updated_at = utcnow()
        event.completed_at = None if should_retry else utcnow()
        db.commit()

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
        event.lease_owner = None
        event.lease_expires_at = None
        event.updated_at = utcnow()
        db.commit()


class ChannelDeliveryRepository:
    def queued_for_event(self, db: Session, event_id: str) -> ChannelDelivery | None:
        return db.scalars(
            select(ChannelDelivery)
            .where(
                ChannelDelivery.event_id == event_id,
                ChannelDelivery.status == "queued",
            )
            .order_by(ChannelDelivery.created_at)
        ).first()

    def claim_queued(self, db: Session, event_id: str) -> ChannelDelivery | None:
        delivery = self.queued_for_event(db, event_id)
        if delivery is None:
            return None
        delivery.status = "pending"
        delivery.attempts += 1
        db.commit()
        db.refresh(delivery)
        return delivery

    def create(
        self,
        db: Session,
        *,
        event_id: str | None,
        request_id: str,
        channel_config_id: str | None = None,
        message_json: str | None = None,
        retry_of_id: str | None = None,
    ) -> ChannelDelivery:
        delivery = ChannelDelivery(
            id=str(uuid4()),
            event_id=event_id,
            channel_config_id=channel_config_id,
            retry_of_id=retry_of_id,
            request_id=request_id,
            message_json=message_json,
            status="pending",
            attempts=1,
        )
        db.add(delivery)
        db.commit()
        db.refresh(delivery)
        return delivery

    def pending_for_event(self, db: Session, event_id: str) -> ChannelDelivery | None:
        return db.scalars(
            select(ChannelDelivery)
            .where(
                ChannelDelivery.event_id == event_id,
                ChannelDelivery.status == "pending",
            )
            .order_by(ChannelDelivery.created_at.desc())
        ).first()

    def get(self, db: Session, delivery_id: str) -> ChannelDelivery | None:
        return db.get(ChannelDelivery, delivery_id)

    def list_recent(self, db: Session, limit: int = 100) -> list[ChannelDelivery]:
        return list(
            db.scalars(
                select(ChannelDelivery)
                .order_by(ChannelDelivery.created_at.desc())
                .limit(limit)
            )
        )

    def queue_retry(
        self, db: Session, delivery: ChannelDelivery, *, allow_unknown: bool
    ) -> ChannelDelivery:
        if delivery.status == "unknown" and not allow_unknown:
            raise ValueError("未知投递可能已经发送，重试必须显式确认")
        if delivery.status not in {"failed", "unknown"}:
            raise ValueError("只有明确失败或未知的投递可以重试")
        if not delivery.event_id or not delivery.message_json:
            raise ValueError("该投递缺少可恢复的事件或消息快照")
        queued = ChannelDelivery(
            id=str(uuid4()),
            event_id=delivery.event_id,
            channel_config_id=delivery.channel_config_id,
            retry_of_id=delivery.id,
            request_id=str(uuid4()),
            message_json=delivery.message_json,
            status="queued",
            attempts=0,
        )
        event = db.get(ChannelEvent, delivery.event_id)
        if event is None:
            raise ValueError("原渠道事件不存在")
        event.status = "responded"
        event.outbound_message_json = delivery.message_json
        event.completed_at = None
        event.last_error = None
        event.updated_at = utcnow()
        db.add(queued)
        db.commit()
        db.refresh(queued)
        return queued

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


class ChannelGroupPolicyRepository:
    def get(
        self, db: Session, channel_config_id: str, external_group_id: str
    ) -> ChannelGroupPolicy | None:
        return db.scalars(
            select(ChannelGroupPolicy).where(
                ChannelGroupPolicy.channel_config_id == channel_config_id,
                ChannelGroupPolicy.external_group_id == external_group_id,
            )
        ).first()

    def list(self, db: Session, channel_config_id: str) -> list[ChannelGroupPolicy]:
        return list(
            db.scalars(
                select(ChannelGroupPolicy)
                .where(ChannelGroupPolicy.channel_config_id == channel_config_id)
                .order_by(ChannelGroupPolicy.external_group_id)
            )
        )

    def upsert(
        self,
        db: Session,
        channel_config_id: str,
        external_group_id: str,
        *,
        enabled: bool,
        require_mention: bool = True,
        tool_allowlist: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> ChannelGroupPolicy:
        policy = self.get(db, channel_config_id, external_group_id)
        if policy is None:
            policy = ChannelGroupPolicy(
                id=str(uuid4()),
                channel_config_id=channel_config_id,
                external_group_id=external_group_id,
            )
            db.add(policy)
        policy.enabled = enabled
        policy.require_mention = require_mention
        policy.tool_allowlist_json = json.dumps(tool_allowlist or [], ensure_ascii=False)
        policy.system_prompt = system_prompt
        db.commit()
        db.refresh(policy)
        return policy

    @staticmethod
    def tool_allowlist(policy: ChannelGroupPolicy) -> list[str]:
        value = json.loads(policy.tool_allowlist_json)
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


class ChannelMediaRepository:
    def create(self, db: Session, **values) -> ChannelMediaAsset:
        asset = ChannelMediaAsset(id=values.pop("id", str(uuid4())), **values)
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset

    def get(self, db: Session, asset_id: str) -> ChannelMediaAsset | None:
        return db.get(ChannelMediaAsset, asset_id)

    def list_cleanup_candidates(self, db: Session) -> list[ChannelMediaAsset]:
        return list(
            db.scalars(
                select(ChannelMediaAsset).order_by(
                    ChannelMediaAsset.expires_at,
                    ChannelMediaAsset.last_accessed_at,
                )
            )
        )
