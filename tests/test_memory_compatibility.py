"""The established MemoryService and indexer imports stay available."""

from zhiyu.application.memories import MemoryService as LegacyMemoryService
from zhiyu.core.memory.indexer import (
    get_index_status as legacy_get_index_status,
    rebuild_index as legacy_rebuild_index,
    sync_changed_index as legacy_sync_changed_index,
)
from zhiyu.memory.indexer import get_index_status, rebuild_index, sync_changed_index
from zhiyu.memory.service import MemoryService


def test_memory_service_compatibility_import():
    assert LegacyMemoryService is MemoryService


def test_memory_indexer_compatibility_imports():
    assert legacy_get_index_status is get_index_status
    assert legacy_rebuild_index is rebuild_index
    assert legacy_sync_changed_index is sync_changed_index
