"""Memory 管理：提取 + 去重 + 存库。"""

from sqlalchemy.orm import Session

from ..database.models import Memory
from ..database.repositories.memory_repository import MemoryRepository
from ..providers.base import AIProvider
from .extractor import extract_candidates


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
    ) -> list[Memory]:
        candidates = await extract_candidates(
            provider,
            model,
            [{"role": "user", "content": user_msg}, {"role": "assistant", "content": assistant_msg}],
        )
        existing = self.repo.list(db)
        saved: list[Memory] = []
        for c in candidates:
            if self._is_duplicate(c["content"], existing):
                continue
            memory = self.repo.create(db, type=c["type"], content=c["content"])
            existing.append(memory)
            saved.append(memory)
        return saved

    @staticmethod
    def _is_duplicate(content: str, existing: list[Memory]) -> bool:
        for m in existing:
            if m.content == content or content in m.content or m.content in content:
                return True
        return False
