"""Canonical memory scope rules shared by extraction and index recovery."""

from zhiyu.infrastructure.database.repositories.identity_repository import LOCAL_IDENTITY_ID

SHARED_USER_MEMORY_TYPES = frozenset({"profile", "preference", "fact", "goal", "project"})


def is_shared_user_memory(memory_type: str, file_path: str | None = None) -> bool:
    return memory_type in SHARED_USER_MEMORY_TYPES and not (file_path or "").endswith("IDENTITY.md")
