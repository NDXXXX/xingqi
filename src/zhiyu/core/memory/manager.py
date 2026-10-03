"""Memory 管理：提取情景观察并以单个事务写入文件 + 索引。"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory, Message
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.providers.base import AIProvider
from .extractor import extract_observations
from .store import MemoryStore


class MemoryManager:
    def __init__(self, store: MemoryStore | None = None) -> None:
        self.repo = MemoryRepository()
        self.store = store or MemoryStore()

    async def extract_and_save(
        self,
        db: Session,
        provider: AIProvider,
        model: str,
        user_msg: str,
        assistant_msg: str,
        identity_id: str,
        *,
        user_message_id: str | None = None,
        history: list[dict] | None = None,
        should_apply: Callable[[], bool] | None = None,
        commit: bool = True,
    ) -> list[Memory]:
        if not identity_id:
            raise ValueError("保存记忆必须指定身份")

        observations = await extract_observations(
            provider,
            model,
            user_message=user_msg,
            assistant_message=assistant_msg,
            history=history or [],
        )
        if not observations:
            return []
        if should_apply is not None and not should_apply():
            return []

        conversation_id = self._conversation_of(db, user_message_id) if user_message_id else None

        changed: list[Memory] = []
        seen: set[tuple[str, str]] = set()
        try:
            for observation in observations:
                if observation["evidence"] not in user_msg:
                    continue
                key = (observation["type"], observation["content"].strip())
                if key in seen:
                    continue
                seen.add(key)
                changed.append(
                    self._write_episodic(db, identity_id, observation, user_message_id, conversation_id)
                )
            if commit:
                db.commit()
            else:
                db.flush()
        except Exception:
            db.rollback()
            raise
        return changed

    def _write_episodic(
        self,
        db: Session,
        identity_id: str,
        observation: dict,
        user_message_id: str | None,
        conversation_id: str | None,
    ) -> Memory:
        path = self.store.daily_path()
        entry = self.store.append(path, observation["content"], meta={"type": observation["type"]})
        return self.repo.create(
            db,
            type=observation["type"],
            content=entry.content,
            identity_id=identity_id,
            source_message_id=user_message_id,
            tier="episodic",
            trust="agent",
            source_kind="message",
            promotion_status="pending",
            conversation_id=conversation_id,
            file_path=path.name,
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
        )

    @staticmethod
    def _conversation_of(db: Session, message_id: str) -> str | None:
        message = db.get(Message, message_id)
        return message.conversation_id if message is not None else None
