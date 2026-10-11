"""Application operations for one-time reminders."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import ScheduledTask, utcnow
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository
from zhiyu.infrastructure.database.repositories.scheduled_task_repository import ScheduledTaskRepository


class ScheduledTaskService:
    def __init__(self, session_factory=SessionLocal) -> None:
        self.session_factory = session_factory
        self.tasks = ScheduledTaskRepository()
        self.channels = ChannelConfigRepository()

    def list(self) -> list[dict]:
        with self.session_factory() as db:
            return [self._dict(item) for item in self.tasks.list(db)]

    def create(self, *, content: str, due_at: datetime, timezone_name: str, channel: str) -> dict:
        normalized, utc_due, channel_values = self._validate(content, due_at, timezone_name, channel)
        with self.session_factory() as db:
            task = self.tasks.create(
                db,
                content=normalized,
                due_at=utc_due,
                timezone=timezone_name,
                channel=channel,
                channel_config_id=channel_values[0],
                target_user_id=channel_values[1],
                enabled=True,
                status="pending",
                attempts=0,
                next_attempt_at=utc_due,
            )
            return self._dict(task)

    def update(self, task_id: str, *, content: str, due_at: datetime, timezone_name: str, channel: str) -> dict:
        normalized, utc_due, channel_values = self._validate(content, due_at, timezone_name, channel)
        with self.session_factory() as db:
            task = self.tasks.get(db, task_id)
            if task is None:
                raise ValueError("提醒不存在")
            if task.status == "sending":
                raise ValueError("提醒正在发送，稍后再编辑")
            task = self.tasks.update(
                db,
                task,
                content=normalized,
                due_at=utc_due,
                timezone=timezone_name,
                channel=channel,
                channel_config_id=channel_values[0],
                target_user_id=channel_values[1],
                enabled=True,
                status="pending",
                attempts=0,
                next_attempt_at=utc_due,
                last_error=None,
                sent_at=None,
            )
            return self._dict(task)

    def set_enabled(self, task_id: str, enabled: bool) -> dict:
        with self.session_factory() as db:
            task = self.tasks.get(db, task_id)
            if task is None:
                raise ValueError("提醒不存在")
            if task.status in {"sending", "due", "delivered", "completed"}:
                raise ValueError("当前提醒状态不能暂停或恢复")
            task = self.tasks.update(
                db, task, enabled=enabled,
                status="pending" if enabled else "paused",
                next_attempt_at=min(task.due_at, utcnow()) if enabled else task.next_attempt_at,
            )
            return self._dict(task)

    def retry(self, task_id: str) -> dict:
        with self.session_factory() as db:
            task = self.tasks.get(db, task_id)
            if task is None:
                raise ValueError("提醒不存在")
            if task.channel != "qq" or task.status != "failed":
                raise ValueError("只有发送失败的 QQ 提醒可以重试")
            task = self.tasks.update(
                db, task, enabled=True, status="pending", attempts=0,
                next_attempt_at=utcnow(), last_error=None,
            )
            return self._dict(task)

    def complete(self, task_id: str) -> None:
        with self.session_factory() as db:
            task = self.tasks.get(db, task_id)
            if task is None:
                raise ValueError("提醒不存在")
            if task.channel != "local" or task.status != "due":
                raise ValueError("只有已到期的本机提醒可以完成")
            self.tasks.update(db, task, enabled=False, status="completed")

    def delete(self, task_id: str) -> None:
        with self.session_factory() as db:
            task = self.tasks.get(db, task_id)
            if task is None:
                raise ValueError("提醒不存在")
            if task.status == "sending":
                raise ValueError("提醒正在发送，稍后再删除")
            self.tasks.delete(db, task)

    def _validate(self, content, due_at, timezone_name, channel):
        normalized = content.strip()
        if not normalized:
            raise ValueError("提醒内容不能为空")
        if len(normalized) > 500:
            raise ValueError("提醒内容不能超过 500 字符")
        try:
            zone = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("无效的时区") from exc
        if due_at.tzinfo is None:
            local_due = due_at.replace(tzinfo=zone)
        else:
            local_due = due_at.astimezone(zone)
        utc_due = local_due.astimezone(timezone.utc).replace(tzinfo=None)
        if utc_due <= utcnow():
            raise ValueError("提醒时间必须晚于当前时间")
        if channel == "local":
            return normalized, utc_due, (None, None)
        if channel != "qq":
            raise ValueError("不支持的提醒渠道")
        with self.session_factory() as db:
            config = self.channels.get(db, "qq")
            if config is None or not config.enabled or not config.owner_user_id:
                raise ValueError("请先配置并启用 QQ 主人账号，才能发送 QQ 提醒")
            return normalized, utc_due, (config.id, config.owner_user_id)

    @staticmethod
    def _dict(task: ScheduledTask) -> dict:
        local_due = task.due_at.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(task.timezone))
        return {
            "id": task.id,
            "content": task.content,
            "due_at": task.due_at.replace(tzinfo=timezone.utc).isoformat(),
            "due_local": local_due.isoformat(),
            "timezone": task.timezone,
            "channel": task.channel,
            "enabled": task.enabled,
            "status": task.status,
            "attempts": task.attempts,
            "last_error": task.last_error,
            "sent_at": task.sent_at.replace(tzinfo=timezone.utc).isoformat() if task.sent_at else None,
        }
