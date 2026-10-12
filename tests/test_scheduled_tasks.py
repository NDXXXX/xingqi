from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.scheduled_tasks.jobs import ScheduledTaskProcessor
from zhiyu.scheduled_tasks.service import ScheduledTaskService
from zhiyu.channels.messages import DeliveryReceipt
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import ScheduledTask, utcnow
from zhiyu.infrastructure.database.repositories.integration_repository import ChannelConfigRepository


def _factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_local_reminder_create_edit_pause_and_resume():
    sessions = _factory()
    service = ScheduledTaskService(sessions)
    due = datetime.now().replace(microsecond=0) + timedelta(hours=1)
    item = service.create(content="交周报", due_at=due, timezone_name="Asia/Shanghai", channel="local")
    assert item["status"] == "pending"
    assert item["timezone"] == "Asia/Shanghai"
    assert service.set_enabled(item["id"], False)["status"] == "paused"
    assert service.set_enabled(item["id"], True)["status"] == "pending"
    updated = service.update(item["id"], content="提交周报", due_at=due + timedelta(hours=1), timezone_name="Asia/Shanghai", channel="local")
    assert updated["content"] == "提交周报"
    assert service.list()[0]["id"] == item["id"]


def test_reminder_rejects_past_time_and_invalid_timezone():
    service = ScheduledTaskService(_factory())
    with pytest.raises(ValueError, match="晚于当前时间"):
        service.create(content="过期", due_at=utcnow() - timedelta(minutes=1), timezone_name="UTC", channel="local")
    with pytest.raises(ValueError, match="时区"):
        service.create(content="时区", due_at=datetime.now() + timedelta(hours=1), timezone_name="Mars/Olympus", channel="local")


def test_qq_reminder_targets_configured_owner_and_rejects_missing_config():
    sessions = _factory()
    service = ScheduledTaskService(sessions)
    due = datetime.now() + timedelta(hours=1)
    with pytest.raises(ValueError, match="配置并启用 QQ"):
        service.create(content="提示", due_at=due, timezone_name="UTC", channel="qq")
    with sessions() as db:
        config = ChannelConfigRepository().upsert(db, "qq", "ws://localhost", None, owner_user_id="123456")
    task = service.create(content="私聊提醒", due_at=due, timezone_name="UTC", channel="qq")
    with sessions() as db:
        saved = db.get(ScheduledTask, task["id"])
        assert saved.channel_config_id == config.id
        assert saved.target_user_id == "123456"


@pytest.mark.asyncio
async def test_processor_marks_local_reminder_due_after_restart():
    sessions = _factory()
    with sessions() as db:
        task = ScheduledTask(
            id="local-due", content="已到期", due_at=utcnow() - timedelta(seconds=1),
            timezone="UTC", channel="local", enabled=True, status="pending", attempts=0,
            next_attempt_at=utcnow(),
        )
        db.add(task); db.commit()
    processor = ScheduledTaskProcessor(sessions, AsyncMock())
    assert await processor.run_once() == 1
    with sessions() as db:
        saved = db.get(ScheduledTask, "local-due")
        assert saved.status == "due"
        assert saved.enabled is False
        assert saved.sent_at is not None


@pytest.mark.asyncio
async def test_processor_delivers_due_qq_reminder_once():
    sessions = _factory()
    with sessions() as db:
        task = ScheduledTask(
            id="qq-due", content="私聊内容", due_at=utcnow() - timedelta(seconds=1),
            timezone="UTC", channel="qq", channel_config_id="cfg", target_user_id="123",
            enabled=True, status="pending", attempts=0, next_attempt_at=utcnow() - timedelta(seconds=1),
        )
        db.add(task); db.commit()
    channels = AsyncMock()
    channels.send_scheduled_private_message.return_value = DeliveryReceipt(status="sent")
    processor = ScheduledTaskProcessor(sessions, channels)
    assert await processor.run_once() == 1
    channels.send_scheduled_private_message.assert_awaited_once_with("cfg", "123", "私聊内容")
    assert await processor.run_once() == 0
    with sessions() as db:
        assert db.get(ScheduledTask, "qq-due").status == "delivered"
