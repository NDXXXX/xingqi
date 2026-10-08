"""本机个人助手的人格与对话规则。"""

from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository


class AssistantProfileService:
    def __init__(self, session_factory=SessionLocal, store: MemoryStore | None = None) -> None:
        self.session_factory = session_factory
        self.store = store or MemoryStore()

    def get(self) -> dict[str, object]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().local(db).id
        return {
            "files": self.store.read_bootstrap_files(identity_id),
            "bootstrap_pending": self.store.bootstrap_pending(identity_id),
        }

    def update(self, name: str, content: str) -> dict[str, object]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().local(db).id
        self.store.write_bootstrap_file(identity_id, name, content)
        return self.get()

    def complete_bootstrap(self) -> dict[str, object]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().local(db).id
        self.store.complete_bootstrap(identity_id)
        return self.get()
