"""Compatibility exports for the established memory indexer import path."""

from zhiyu.memory.indexer import get_index_status, rebuild_index, sync_changed_index

__all__ = ["get_index_status", "rebuild_index", "sync_changed_index"]
