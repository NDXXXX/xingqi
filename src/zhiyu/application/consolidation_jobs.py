"""后台记忆巩固：把达到阈值的待处理情景观察晋升为长期核心。

触发条件（任一）：
- 待处理情景观察 >= PENDING_THRESHOLD；
- 最旧待处理观察超过 STALE_HOURS；
- 手动 ``memory consolidate``。
"""

import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from zhiyu.core.memory.consolidation import apply_consolidation, propose
from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.core.memory.retriever import build_query_plan, _lexical_similarity
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.router import provider_router
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.models import (
    ForgottenConversation,
    Memory,
    MemoryConsolidationRun,
    MemoryRecallEvent,
    utcnow,
)
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository

logger = logging.getLogger(__name__)

PENDING_THRESHOLD = 20
STALE_HOURS = 24


class ConsolidationProcessor:
    def __init__(self, session_factory=SessionLocal, store: MemoryStore | None = None) -> None:
        self.session_factory = session_factory
        self.store = store or MemoryStore()

    async def run_sweep(
        self,
        *,
        identity_id: str | None = None,
        dry_run: bool = True,
        force: bool = False,
    ) -> dict:
        with self.session_factory() as db:
            identity_id = identity_id or IdentityRepository().local(db).id
            rebuild_index(db, self.store, identity_id)
            pending = self._pending(db, identity_id)
            if not pending:
                return {"status": "skipped", "pending": 0}
            if not force and not self._threshold_met(pending):
                return {"status": "skipped", "pending": len(pending)}
            candidates = self._eligible(db, identity_id, pending)
            if not candidates:
                return {
                    "status": "skipped",
                    "pending": len(pending),
                    "eligible": 0,
                }
            provider_config, model = self._default_provider_model(db)
            core = MemoryRepository().list_owned(db, identity_id, tier="core", statuses=("active",))

        client = provider_router.get_provider(provider_config)
        operations = await propose(client, model.model_name, candidates, core)

        with self.session_factory() as db:
            stats = apply_consolidation(
                db, self.store, identity_id, operations, dry_run=dry_run
            )
            self._record_run(
                db, identity_id, stats, "dry_run" if dry_run else "applied"
            )
        return {"status": "ok", **stats}

    async def run_due(self, *, dry_run: bool = False) -> dict[str, dict]:
        with self.session_factory() as db:
            identity_ids = list(
                db.scalars(
                    select(Memory.identity_id)
                    .where(
                        Memory.tier == "episodic",
                        Memory.status == "active",
                        Memory.promotion_status == "pending",
                        Memory.identity_id.is_not(None),
                    )
                    .distinct()
                )
            )
        results = {}
        for identity_id in identity_ids:
            results[identity_id] = await self.run_sweep(
                identity_id=identity_id, dry_run=dry_run
            )
        return results

    async def run_forever(self, interval_seconds: int) -> None:
        while True:
            try:
                result = await self.run_due(dry_run=False)
                logger.info("consolidation sweep: %s", result)
            except Exception as exc:  # 单次失败不终止守护循环
                logger.warning("consolidation sweep failed: %s", exc)
            await asyncio.sleep(interval_seconds)

    def list_runs(self, limit: int = 10) -> list[MemoryConsolidationRun]:
        with self.session_factory() as db:
            identity_id = IdentityRepository().local(db).id
            return list(
                db.scalars(
                    select(MemoryConsolidationRun)
                    .where(MemoryConsolidationRun.identity_id == identity_id)
                    .order_by(MemoryConsolidationRun.created_at.desc())
                    .limit(limit)
                )
            )

    def _pending(self, db, identity_id: str):
        return [
            item
            for item in MemoryRepository().list_owned(
                db, identity_id, tier="episodic", statuses=("active",)
            )
            if item.promotion_status == "pending" and item.trust in ("owner", "agent")
        ]

    def _eligible(self, db, identity_id: str, candidates: list[Memory]) -> list[Memory]:
        """在模型调用前执行可审计的晋升门槛。"""
        forgotten = set(
            db.scalars(
                select(ForgottenConversation.conversation_id).where(
                    ForgottenConversation.identity_id == identity_id
                )
            )
        )
        valid = [
            item
            for item in candidates
            if item.conversation_id not in forgotten and self._entry_is_current(identity_id, item)
        ]
        eligible: list[Memory] = []
        for candidate in valid:
            query_hashes = set(
                db.scalars(
                    select(MemoryRecallEvent.query_hash).where(
                        MemoryRecallEvent.identity_id == identity_id,
                        MemoryRecallEvent.memory_id == candidate.id,
                    )
                )
            )
            recalled_enough = len(query_hashes) >= 3
            active_work_referenced = (
                candidate.type in ("goal", "project") and bool(query_hashes)
            )
            repeated = any(
                other.id != candidate.id
                and self._independent(candidate, other)
                and self._semantically_related(candidate.content, other.content)
                for other in valid
            )
            if (
                candidate.trust == "owner"
                or recalled_enough
                or active_work_referenced
                or repeated
            ):
                eligible.append(candidate)
        return eligible

    def _entry_is_current(self, identity_id: str, memory: Memory) -> bool:
        if not memory.file_path or not memory.entry_key:
            return False
        try:
            path = self.store.resolve_relative(memory.file_path)
        except ValueError:
            return False
        return self.store.is_managed_path(identity_id, path) and (
            self.store.index_by_id(path, memory.entry_key) is not None
        )

    @staticmethod
    def _independent(left: Memory, right: Memory) -> bool:
        if left.conversation_id and right.conversation_id:
            return left.conversation_id != right.conversation_id
        left_time = left.observed_at or left.created_at
        right_time = right.observed_at or right.created_at
        return left_time.date() != right_time.date()

    @staticmethod
    def _semantically_related(left: str, right: str) -> bool:
        plan = build_query_plan(left)
        return max(
            (_lexical_similarity(variant, right) for variant in plan.variants),
            default=0.0,
        ) >= 0.18

    @staticmethod
    def _threshold_met(candidates) -> bool:
        if len(candidates) >= PENDING_THRESHOLD:
            return True
        if candidates:
            oldest = min(item.observed_at or item.created_at for item in candidates)
            return utcnow() - oldest > timedelta(hours=STALE_HOURS)
        return False

    @staticmethod
    def _default_provider_model(db):
        providers = [
            provider
            for provider in ProviderRepository().list(db)
            if provider.enabled and provider.configured
        ]
        if not providers:
            raise ValueError("没有可用的 Provider，请先运行 zhiyu provider add")
        default = SettingRepository().get(db, "default_model") or {}
        provider = next(
            (item for item in providers if item.id == default.get("provider_id")), providers[0]
        )
        enabled = [model for model in provider.models if model.enabled]
        if not enabled:
            raise ValueError("Provider 未配置可用模型")
        model = next((item for item in enabled if item.id == default.get("model_id")), enabled[0])
        return provider, model

    @staticmethod
    def _record_run(db, identity_id: str, stats: dict, status: str) -> None:
        db.add(
            MemoryConsolidationRun(
                id=str(uuid4()),
                identity_id=identity_id,
                status=status,
                candidate_count=stats.get("candidate_count", 0),
                promoted_count=stats.get("promoted_count", 0),
                merged_count=stats.get("merged_count", 0),
                superseded_count=stats.get("superseded_count", 0),
                skipped_count=stats.get("skipped_count", 0),
                summary=(
                    f"候选 {stats.get('candidate_count', 0)}："
                    f"晋升 {stats.get('promoted_count', 0)}，"
                    f"替换 {stats.get('superseded_count', 0)}，"
                    f"忽略 {stats.get('skipped_count', 0)}"
                ),
                finished_at=utcnow(),
            )
        )
        db.commit()
