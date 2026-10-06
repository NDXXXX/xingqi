"""Read-only memory application operations."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from zhiyu.core.memory.freshness import needs_confirmation
from zhiyu.core.memory.retriever import hybrid_rank
from zhiyu.core.providers.embedding import load_config as load_embedding_config
from zhiyu.core.providers.embedding import resolve_api_key
from zhiyu.infrastructure.database.models import MemoryConsolidationRun, MemoryMutation, MemoryRecallEvent
from zhiyu.application.memory_shared import MemoryOperations, MemorySummary, _summary


class MemoryQueryService(MemoryOperations):
    """Query and explain memory state."""

    def list(self, *, include_inactive: bool = False, tier: str | None = None) -> list[MemorySummary]:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            statuses = None if include_inactive else ("active",)
            return [
                _summary(db, item)
                for item in self.memories.list_owned(db, identity_id, statuses=statuses, tier=tier)
                if include_inactive
                or item.tier == "core"
                or item.promotion_status in {"pending", "deferred"}
            ]

    def search(
        self, query: str, *, include_inactive: bool = False, tier: str | None = None
    ) -> list[MemorySummary]:
        needle = query.strip().lower()
        if not needle:
            raise ValueError("搜索内容不能为空")
        return [
            item
            for item in self.list(include_inactive=include_inactive, tier=tier)
            if needle in item.content.lower()
        ]

    def get(self, memory_id: str) -> MemorySummary | None:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            memory = self.memories.get_owned(db, identity_id, memory_id)
            return _summary(db, memory) if memory is not None else None

    def recall_explain(self, query: str) -> dict:
        if not query.strip():
            raise ValueError("查询不能为空")
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            self._sync(db, identity_id)
            memories = [
                *self.memories.list_visible(db, identity_id, tier="core"),
                *self.memories.list_owned(db, identity_id, tier="episodic"),
            ]
            memories = [
                item
                for item in memories
                if item.promotion_status not in {"promoted", "rejected", "deferred"}
                and not needs_confirmation(item)
            ]
            trace = hybrid_rank(db, query, memories)
            return {
                "query_plan": {
                    "normalized": trace.plan.normalized,
                    "variants": trace.plan.variants,
                    "temporal_intent": trace.plan.temporal_intent,
                    "recall_intent": trace.plan.recall_intent,
                },
                "candidates": [
                    {
                        "id": item.memory.id,
                        "type": item.memory.type,
                        "tier": item.memory.tier,
                        "channels": item.channels,
                        "rrf_score": item.rrf_score,
                        "confidence": item.confidence,
                        "filtered_reason": item.filtered_reason,
                    }
                    for item in trace.candidates
                ],
                "selected_ids": [item.memory.id for item in trace.selected],
            }

    def status(self) -> dict[str, int | str]:
        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            result: dict[str, int | str] = {
                f"jobs_{key}": value for key, value in self.jobs.counts(db).items()
            }
            mutation_counts = db.execute(
                select(MemoryMutation.status, func.count(MemoryMutation.id))
                .where(MemoryMutation.identity_id == identity_id)
                .group_by(MemoryMutation.status)
            ).all()
            for status, count in mutation_counts:
                result[f"mutations_{status}"] = count
            for status in ("prepared", "file_applied", "failed"):
                result.setdefault(f"mutations_{status}", 0)
            last_recall = db.scalars(
                select(MemoryRecallEvent).order_by(
                    MemoryRecallEvent.created_at.desc()
                ).where(MemoryRecallEvent.identity_id == identity_id)
            ).first()
            if last_recall is not None:
                result["last_recall_mode"] = last_recall.recall_mode
                result["last_recall_injected_count"] = db.scalar(
                    select(func.count(MemoryRecallEvent.id)).where(
                        MemoryRecallEvent.identity_id == last_recall.identity_id,
                        MemoryRecallEvent.query_hash == last_recall.query_hash,
                        MemoryRecallEvent.created_at
                        >= last_recall.created_at - timedelta(seconds=2),
                    )
                ) or 0
            config = load_embedding_config(db)
            if config is None:
                result["embedding"] = "lexical_only:not_configured"
            elif not resolve_api_key(config.api_key_ref):
                result["embedding"] = "lexical_only:missing_credentials"
            else:
                result["embedding"] = f"configured:{config.model}"
            return result

    def consolidation_runs(self, limit: int = 5) -> list[dict]:
        from zhiyu.infrastructure.database.models import MemoryConsolidationRun

        with self.session_factory() as db:
            identity_id = self.identities.local(db).id
            rows = db.scalars(
                select(MemoryConsolidationRun)
                .where(MemoryConsolidationRun.identity_id == identity_id)
                .order_by(MemoryConsolidationRun.created_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": item.id,
                    "status": item.status,
                    "candidate_count": item.candidate_count,
                    "promoted_count": item.promoted_count,
                    "merged_count": item.merged_count,
                    "superseded_count": item.superseded_count,
                    "skipped_count": item.skipped_count,
                    "summary": item.summary,
                    "details": item.details_json,
                    "last_error": item.last_error,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "finished_at": item.finished_at.isoformat() if item.finished_at else None,
                }
                for item in rows
            ]
