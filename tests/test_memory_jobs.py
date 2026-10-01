"""持久化记忆提取任务测试。"""

from unittest.mock import AsyncMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.memories import MemoryService
from zhiyu.application.memory_jobs import MemoryJobProcessor
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


class EmptyProvider(AIProvider):
    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content="[]")


class FakeRouter:
    def get_provider(self, _config):
        return EmptyProvider("fake-key")


def _queued_job():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        provider = ProviderRepository().create(
            db,
            name="Fake",
            provider_type="openai",
            api_key_ref="env:FAKE_KEY",
        )
        identity = IdentityRepository().local(db)
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity.id
        )
        user = MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content="我喜欢咖啡"
        )
        assistant = MessageRepository().create(
            db, conversation_id=conversation.id, role="assistant", content="记住了"
        )
        job = MemoryJobRepository().create(
            db,
            user_message_id=user.id,
            assistant_message_id=assistant.id,
            identity_id=identity.id,
            provider_id=provider.id,
            model=provider.models[0].model_name,
        )
        db.commit()
        return factory, job.id, user.id, identity.id


async def test_job_completes_and_does_not_duplicate_applied_source():
    factory, job_id, user_id, identity_id = _queued_job()
    manager = AsyncMock()
    with factory() as db:
        MemoryRepository().create(
            db,
            type="preference",
            content="用户喜欢咖啡",
            identity_id=identity_id,
            source_message_id=user_id,
        )
        db.commit()

    result = await MemoryJobProcessor(factory, FakeRouter(), manager).process_pending()

    assert result["completed"] == 1
    manager.extract_and_save.assert_not_awaited()
    with factory() as db:
        assert MemoryJobRepository().get(db, job_id).status == "completed"


async def test_failed_job_stops_after_three_attempts_and_can_retry():
    factory, job_id, _user_id, _identity_id = _queued_job()
    manager = AsyncMock()
    manager.extract_and_save.side_effect = RuntimeError("模型暂时不可用")
    processor = MemoryJobProcessor(factory, FakeRouter(), manager)

    for _ in range(3):
        await processor.process_pending()

    with factory() as db:
        job = MemoryJobRepository().get(db, job_id)
        assert job.status == "failed"
        assert job.attempts == 3
        assert "模型暂时不可用" in job.last_error

    assert processor.retry_failed() == 1
    with factory() as db:
        job = MemoryJobRepository().get(db, job_id)
        assert job.status == "pending"
        assert job.attempts == 0


def test_manual_edit_cancels_pending_jobs_for_identity():
    factory, job_id, _user_id, identity_id = _queued_job()
    with factory() as db:
        memory = MemoryRepository().create(
            db, type="preference", content="用户喜欢咖啡", identity_id=identity_id
        )
        db.commit()
        memory_id = memory.id

    MemoryService(factory).edit(memory_id, content="用户不喝咖啡")

    with factory() as db:
        assert MemoryJobRepository().get(db, job_id).status == "cancelled"


def test_interrupted_job_returns_to_pending():
    factory, job_id, _user_id, _identity_id = _queued_job()
    with factory() as db:
        assert MemoryJobRepository().claim(db, job_id).status == "processing"
    with factory() as db:
        assert MemoryJobRepository().recover_interrupted(db, stale_after_seconds=0) == 1
        assert MemoryJobRepository().get(db, job_id).status == "pending"
