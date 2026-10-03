"""可恢复的后台记忆提取任务。"""

import asyncio
import logging

from zhiyu.core.memory.deep_recall import is_forgotten
from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.providers.router import ProviderRouter, provider_router
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import Message
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


logger = logging.getLogger(__name__)


class MemoryJobProcessor:
    def __init__(
        self,
        session_factory=SessionLocal,
        providers: ProviderRouter = provider_router,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.providers = providers
        self.memory_manager = memory_manager or MemoryManager()
        self.jobs = MemoryJobRepository()
        self.memories = MemoryRepository()
        self._task: asyncio.Task | None = None

    def kick(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.process_pending(recover=True))

    async def wait_idle(self) -> None:
        if self._task is not None:
            await self._task

    async def process_pending(self, *, recover: bool = True) -> dict[str, int]:
        if recover:
            with self.session_factory() as db:
                self.jobs.recover_interrupted(db)
        result = {"completed": 0, "retried": 0, "failed": 0, "cancelled": 0}
        seen: set[str] = set()
        while True:
            with self.session_factory() as db:
                pending_ids = [
                    item.id
                    for item in self.jobs.list_by_status(db, "pending")
                    if item.id not in seen
                ]
            if not pending_ids:
                break
            for job_id in pending_ids:
                seen.add(job_id)
                status = await self._process_one(job_id)
                result[status] = result.get(status, 0) + 1
        if result["completed"]:
            try:
                from zhiyu.application.consolidation_jobs import ConsolidationProcessor

                await ConsolidationProcessor(
                    self.session_factory, self.memory_manager.store
                ).run_due(dry_run=False)
            except Exception as exc:
                logger.warning("memory consolidation scheduling failed: %s", exc)
        return result

    async def _process_one(self, job_id: str) -> str:
        with self.session_factory() as db:
            job = self.jobs.claim(db, job_id)
            if job is None:
                return "cancelled"
            user = db.get(Message, job.user_message_id)
            assistant = db.get(Message, job.assistant_message_id) if job.assistant_message_id else None
            provider_config = ProviderRepository().get(db, job.provider_id)
            if user is None:
                self.jobs.finish(db, job, "cancelled")
                return "cancelled"
            if is_forgotten(db, user.conversation_id, job.identity_id):
                self.jobs.finish(db, job, "cancelled")
                return "cancelled"
            messages = MessageRepository().list_by_conversation(db, user.conversation_id)
            user_index = next(
                (index for index, message in enumerate(messages) if message.id == user.id), 0
            )
            history = [
                {"role": message.role, "content": message.content}
                for message in messages[max(0, user_index - 4) : user_index]
            ]
            data = {
                "user_message_id": user.id,
                "user_message": user.content,
                "assistant_message": assistant.content if assistant is not None else "",
                "identity_id": job.identity_id,
                "model": job.model,
            }

        def should_apply() -> bool:
            with self.session_factory() as check_db:
                current = self.jobs.get(check_db, job_id)
                return current is not None and current.status == "processing"

        try:
            if provider_config is None or not provider_config.enabled:
                raise ValueError("任务对应的 Provider 不可用")
            client = self.providers.get_provider(provider_config)
            if not client.api_key:
                raise ValueError("任务对应的 Provider 凭据不可用")
            with self.session_factory() as db:
                if isinstance(self.memory_manager, MemoryManager):
                    rebuild_index(
                        db, self.memory_manager.store, data["identity_id"]
                    )
                if not self.memories.has_source_action(
                    db, data["identity_id"], data["user_message_id"]
                ):
                    await self.memory_manager.extract_and_save(
                        db,
                        client,
                        data["model"],
                        data["user_message"],
                        data["assistant_message"],
                        data["identity_id"],
                        user_message_id=data["user_message_id"],
                        history=history,
                        should_apply=should_apply,
                        commit=False,
                    )
                current = self.jobs.get(db, job_id)
                if current is None or current.status == "cancelled":
                    db.rollback()
                    return "cancelled"
                self.jobs.finish(db, current, "completed")
            return "completed"
        except asyncio.CancelledError:
            with self.session_factory() as db:
                self.jobs.release(db, job_id)
            raise
        except Exception as exc:
            logger.warning("memory job %s failed: %s", job_id, exc)
            with self.session_factory() as db:
                current = self.jobs.get(db, job_id)
                if current is None or current.status == "cancelled":
                    return "cancelled"
                status = "failed" if current.attempts >= 3 else "pending"
                self.jobs.finish(db, current, status, str(exc))
                return "failed" if status == "failed" else "retried"

    def status(self) -> dict[str, int]:
        with self.session_factory() as db:
            return self.jobs.counts(db)

    def retry_failed(self) -> int:
        with self.session_factory() as db:
            return self.jobs.retry_failed(db)
