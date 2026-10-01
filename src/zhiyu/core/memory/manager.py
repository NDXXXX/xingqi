"""Memory 管理：提取、校验并以单个事务应用生命周期操作。"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.providers.base import AIProvider
from .extractor import extract_operations
from .retriever import retrieve


class MemoryManager:
    def __init__(self) -> None:
        self.repo = MemoryRepository()

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

        owned = self.repo.list_owned(db, identity_id)
        relevant = retrieve(user_msg, owned, top_k=15)
        candidates: list[Memory] = []
        seen: set[str] = set()
        for memory in [*relevant, *owned[:20]]:
            if memory.id not in seen:
                candidates.append(memory)
                seen.add(memory.id)
            if len(candidates) == 20:
                break
        serialized = [
            {
                "id": item.id,
                "type": item.type,
                "content": item.content,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in candidates
        ]
        snapshots = {item["id"]: item["updated_at"] for item in serialized}

        db.rollback()
        operations = await extract_operations(
            provider,
            model,
            user_message=user_msg,
            assistant_message=assistant_msg,
            history=history or [],
            memories=serialized,
        )
        if not operations:
            return []
        if should_apply is not None and not should_apply():
            return []

        target_ids = [op["target_id"] for op in operations if "target_id" in op]
        if len(target_ids) != len(set(target_ids)):
            return []

        changed: list[Memory] = []
        try:
            for operation in operations:
                if operation["evidence"] not in user_msg:
                    continue
                action = operation["action"]
                if action == "add":
                    if self._is_duplicate(operation["content"], owned, operation["type"]):
                        continue
                    memory = self.repo.create(
                        db,
                        type=operation["type"],
                        content=operation["content"],
                        identity_id=identity_id,
                        source_message_id=user_message_id,
                    )
                    owned.append(memory)
                    changed.append(memory)
                    continue

                target = self.repo.get_owned(db, identity_id, operation["target_id"])
                if (
                    target is None
                    or target.status != "active"
                    or target.id not in snapshots
                    or target.updated_at.isoformat() != snapshots[target.id]
                ):
                    continue
                if action == "complete":
                    if target.type not in ("goal", "project"):
                        continue
                    self.repo.update(
                        db, target, status="completed", status_source_message_id=user_message_id
                    )
                    changed.append(target)
                elif action == "invalidate":
                    self.repo.update(
                        db, target, status="invalidated", status_source_message_id=user_message_id
                    )
                    changed.append(target)
                elif action == "replace" and operation["type"] == target.type:
                    self.repo.update(
                        db, target, status="superseded", status_source_message_id=user_message_id
                    )
                    memory = self.repo.create(
                        db,
                        type=target.type,
                        content=operation["content"],
                        identity_id=identity_id,
                        source_message_id=user_message_id,
                        supersedes_id=target.id,
                    )
                    owned.append(memory)
                    changed.extend((target, memory))
            if commit:
                db.commit()
            else:
                db.flush()
        except Exception:
            db.rollback()
            raise
        return changed

    @staticmethod
    def _is_duplicate(
        content: str, existing: list[Memory], memory_type: str | None = None
    ) -> bool:
        normalized = content.strip()
        return any(
            item.status == "active"
            and (memory_type is None or item.type == memory_type)
            and item.content.strip() == normalized
            for item in existing
        )
