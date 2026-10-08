"""Deterministic, source-scoped reminders from explicit owner messages."""

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from zhiyu.core.memory.retriever import normalize_text
from zhiyu.core.memory.safety import contains_secret
from zhiyu.infrastructure.database.models import StandingIntent, utcnow


_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_EVENT = re.compile(
    r"^\s*(?:请)?(?:下次|以后)(?:再)?(?:聊|谈|提到)(?P<topic>[^，,。！？?]{1,32}?)(?:时|的时候)[，, ]*(?:请)?提醒我(?P<content>.+?)\s*[。.!！]?\s*$"
)
_TIME = re.compile(
    r"^\s*(?:请)?(?:在)?(?P<day>明天|后天|周[一二三四五六日天])"
    r"(?P<period>上午|下午|晚上)?(?:(?P<hour>\d{1,2})点(?P<minute>\d{1,2})?分?)?"
    r"[，, ]*(?:请)?提醒我(?P<content>.+?)\s*[。.!！]?\s*$"
)
_WEEKDAY = {value: index for index, value in enumerate("一二三四五六日")}
_COOLDOWN = timedelta(hours=24)
_LIFETIME = timedelta(days=90)


def parse_intent(message: str, *, now: datetime | None = None) -> tuple[str, str | None, str, datetime | None] | None:
    """Only explicit supported phrasings create reminders; returned times are naive UTC."""
    event = _EVENT.fullmatch(message)
    if event:
        topic = event.group("topic").strip()
        content = event.group("content").strip()
        if topic and 1 <= len(content) <= 200 and not contains_secret(content):
            return "event", topic, content, None
        return None
    timed = _TIME.fullmatch(message)
    if not timed:
        return None
    content = timed.group("content").strip()
    if not 1 <= len(content) <= 200 or contains_secret(content):
        return None
    local_now = (now or datetime.now(_LOCAL_TZ)).astimezone(_LOCAL_TZ)
    day = timed.group("day")
    hour = int(timed.group("hour")) if timed.group("hour") else {
        "上午": 9, "下午": 15, "晚上": 20,
    }.get(timed.group("period"), 9)
    minute = int(timed.group("minute") or 0)
    if timed.group("period") in {"下午", "晚上"} and hour < 12:
        hour += 12
    if hour > 23 or minute > 59:
        return None
    if day == "明天":
        offset = 1
    elif day == "后天":
        offset = 2
    else:
        weekday = _WEEKDAY["日" if day[-1] == "天" else day[-1]]
        offset = (weekday - local_now.weekday()) % 7
    due = (local_now + timedelta(days=offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if due <= local_now:
        due += timedelta(days=7)
    return "time", None, content, due.astimezone(timezone.utc).replace(tzinfo=None)


class StandingIntentService:
    def record(self, db, conversation, message, text: str) -> str | None:
        if not conversation.identity_id or not (
            conversation.channel == "local" or (
                conversation.channel == "qq" and conversation.external_conversation_type == "private"
            )
        ):
            return None
        existing = db.scalars(select(StandingIntent.id).where(
            StandingIntent.source_message_id == message.id
        )).first()
        if existing:
            return None
        parsed = parse_intent(text)
        if parsed:
            kind, topic, content, due_at = parsed
            db.add(StandingIntent(
                id=str(uuid4()), identity_id=conversation.identity_id,
                source_message_id=message.id, source_conversation_id=conversation.id,
                kind=kind, topic=topic, content=content,
                channel=conversation.channel,
                channel_config_id=conversation.channel_config_id,
                target_id=(conversation.external_user_id if conversation.channel == "qq" else None),
                due_at=due_at, expires_at=utcnow() + _LIFETIME,
                fire_count=0, status="active",
            ))
            db.commit()
            return (
                f"已设置下次聊到“{topic}”时提醒：{content}"
                if kind == "event" else f"已设置提醒：{content}"
            )
        cancelled = re.fullmatch(r"\s*取消提醒(?:我)?[：: ]*(.{1,100})\s*", text)
        if cancelled:
            needle = normalize_text(cancelled.group(1))
            rows = self._active(db, conversation.identity_id)
            matches = [item for item in rows if item.channel == conversation.channel
            and (conversation.channel != "qq" or (
                item.target_id == conversation.external_user_id
                and item.channel_config_id == conversation.channel_config_id
            )) and (
                needle in normalize_text(item.content)
                or (item.topic and needle in normalize_text(item.topic))
            )]
            for item in matches:
                item.status = "cancelled"
            if matches:
                db.commit()
                return f"已取消 {len(matches)} 条提醒"
        return None

    def due_for_turn(self, db, conversation, query: str, source_message_id: str) -> list[StandingIntent]:
        if not conversation.identity_id:
            return []
        now = utcnow()
        normalized = normalize_text(query)
        return [
            item for item in self._active(db, conversation.identity_id)
            if item.source_message_id != source_message_id
            and item.channel == conversation.channel
            and (conversation.channel != "qq" or (
                item.target_id == conversation.external_user_id
                and item.channel_config_id == conversation.channel_config_id
            ))
            and self._ready(item, now)
            and (item.kind == "time" and item.due_at is not None and item.due_at <= now
                 or item.kind == "event" and item.topic is not None
                 and normalize_text(item.topic) in normalized)
        ][:3]

    def due_qq(self, db) -> list[StandingIntent]:
        now = utcnow()
        return [
            item for item in db.scalars(select(StandingIntent).where(
                StandingIntent.channel == "qq",
                StandingIntent.kind == "time",
                StandingIntent.status == "active",
                StandingIntent.due_at <= now,
            ))
            if self._ready(item, now)
        ]

    def due_local(self, db) -> list[StandingIntent]:
        now = utcnow()
        return [
            item for item in db.scalars(select(StandingIntent).where(
                StandingIntent.channel == "local",
                StandingIntent.kind == "time",
                StandingIntent.status == "active",
                StandingIntent.due_at <= now,
            ))
            if self._ready(item, now)
        ]

    @staticmethod
    def recent_local(db, identity_id: str) -> list[dict[str, str]]:
        cutoff = utcnow() - timedelta(days=1)
        rows = db.scalars(select(StandingIntent).where(
            StandingIntent.identity_id == identity_id,
            StandingIntent.channel == "local",
            StandingIntent.kind == "time",
            StandingIntent.last_fired_at >= cutoff,
        ).order_by(StandingIntent.last_fired_at.desc()).limit(10))
        return [
            {
                "id": item.id,
                "content": item.content,
                "conversation_id": item.source_conversation_id,
                "fired_at": item.last_fired_at.isoformat(),
            }
            for item in rows
        ]

    @staticmethod
    def mark_fired(db, intent_ids: list[str]) -> None:
        now = utcnow()
        for item in db.scalars(select(StandingIntent).where(StandingIntent.id.in_(intent_ids))):
            if item.status != "active" or not StandingIntentService._ready(item, now):
                continue
            item.fire_count += 1
            item.last_fired_at = now
            if item.kind == "time" or item.fire_count >= 3:
                item.status = "completed"

    @staticmethod
    def _ready(item: StandingIntent, now: datetime) -> bool:
        return (
            item.status == "active" and item.fire_count < 3
            and item.expires_at > now
            and (item.last_fired_at is None or now - item.last_fired_at >= _COOLDOWN)
        )

    @staticmethod
    def _active(db, identity_id: str) -> list[StandingIntent]:
        return list(db.scalars(select(StandingIntent).where(
            StandingIntent.identity_id == identity_id,
            StandingIntent.status == "active",
        )))
