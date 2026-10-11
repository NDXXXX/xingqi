"""Deliver due reminders from the persistent task queue."""

import logging

from zhiyu.application.channels import ChannelService
from zhiyu.infrastructure.database.models import utcnow
from zhiyu.infrastructure.database.repositories.scheduled_task_repository import ScheduledTaskRepository


logger = logging.getLogger(__name__)


class ScheduledTaskProcessor:
    def __init__(self, session_factory, channels: ChannelService) -> None:
        self.session_factory = session_factory
        self.channels = channels
        self.tasks = ScheduledTaskRepository()

    async def run_once(self) -> int:
        now = utcnow()
        with self.session_factory() as db:
            local = self.tasks.due_local(db, now)
            qq_ids = self.tasks.claim_due_qq(db, now)
        delivered = len(local)
        for task_id in qq_ids:
            with self.session_factory() as db:
                task = self.tasks.get(db, task_id)
                if task is None:
                    continue
                config_id, target, content = task.channel_config_id, task.target_user_id, task.content
            try:
                if not config_id or not target:
                    raise ValueError("QQ 提醒缺少渠道或主人配置")
                receipt = await self.channels.send_scheduled_private_message(config_id, target, content)
                if receipt.status != "sent":
                    raise ConnectionError(receipt.error or f"QQ 消息投递状态：{receipt.status}")
                status, error = "delivered", None
                delivered += 1
            except Exception as exc:
                status, error = "failed", str(exc)[:500]
                logger.warning("Scheduled QQ reminder %s failed: %s", task_id, error)
            with self.session_factory() as db:
                task = self.tasks.get(db, task_id)
                if task is not None and task.status == "sending":
                    self.tasks.update(db, task, status=status, enabled=False, sent_at=utcnow(), last_error=error)
        return delivered

    async def run_forever(self, interval: float = 10) -> None:
        import asyncio

        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled reminder sweep failed")
            await asyncio.sleep(interval)
