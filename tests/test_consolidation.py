"""记忆巩固（dreaming sweep）测试。"""

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.core.memory.consolidation import apply_consolidation, parse_consolidation
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.infrastructure.database.models import MemoryRecallEvent, utcnow
from zhiyu.core.memory.freshness import needs_confirmation


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _candidate(db, store, identity_id, type, content):
    path = store.daily_path(identity_id=identity_id)
    entry = store.append(path, content, meta={"type": type})
    return MemoryRepository().create(
        db,
        type=type,
        content=content,
        identity_id=identity_id,
        tier="episodic",
        trust="agent",
        source_kind="message",
        promotion_status="pending",
        file_path=store.relative_path(path),
        line_start=entry.line_start,
        line_end=entry.line_end,
        content_hash=entry.hash,
        entry_key=entry.id,
    )


def _core(db, store, identity_id, type, content):
    path = store.core_path_for(identity_id)
    entry = store.append(path, content, meta={"type": type})
    return MemoryRepository().create(
        db,
        type=type,
        content=entry.content,
        identity_id=identity_id,
        tier="core",
        trust="agent",
        source_kind="consolidation",
        file_path=store.relative_path(path),
        line_start=entry.line_start,
        line_end=entry.line_end,
        content_hash=entry.hash,
        entry_key=entry.id,
    )


def test_parse_consolidation_accepts_valid():
    text = (
        '[{"action":"add_core","candidate_ids":["a","b"],"type":"preference",'
        '"content":"不推荐咖啡","importance":8},'
        '{"action":"ignore","candidate_ids":["c"]}]'
    )
    ops = parse_consolidation(text)
    assert len(ops) == 2
    assert ops[0]["action"] == "add_core"
    assert ops[0]["candidate_ids"] == ["a", "b"]
    assert ops[1]["action"] == "ignore"


def test_parse_consolidation_rejects_invalid():
    assert parse_consolidation('[{"action":"add_core","type":"preference","content":"x"}]') == []
    assert parse_consolidation('[{"action":"supersede_core","candidate_ids":["a"]}]') == []


def test_apply_promotes_candidates_to_core(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        a = _candidate(db, store, identity_id, "preference", "下午不再喝咖啡")
        b = _candidate(db, store, identity_id, "preference", "以后别推荐咖啡")
        db.commit()

        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "add_core",
                    "candidate_ids": [a.id, b.id],
                    "type": "preference",
                    "content": "不向用户推荐咖啡",
                    "importance": 8,
                }
            ],
        )

        assert stats["promoted_count"] == 1
        assert stats["candidate_count"] == 2
        cores = MemoryRepository().list_owned(db, identity_id, tier="core")
        assert [item.content for item in cores] == ["不向用户推荐咖啡"]
        assert cores[0].trust == "agent"
        assert cores[0].source_kind == "consolidation"
        for candidate in (a, b):
            fresh = MemoryRepository().get(db, candidate.id)
            assert fresh.promotion_status == "promoted"
            assert fresh.promoted_to_id == cores[0].id
        assert "不向用户推荐咖啡" in store.core_path_for(identity_id).read_text(
            encoding="utf-8"
        )


def test_apply_supersedes_old_core(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        old = _core(db, store, identity_id, "preference", "用户喜欢咖啡")
        candidate = _candidate(db, store, identity_id, "preference", "用户戒咖啡了")
        db.commit()

        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "supersede_core",
                    "target_id": old.id,
                    "candidate_ids": [candidate.id],
                    "type": "preference",
                    "content": "用户已戒咖啡",
                    "importance": 7,
                }
            ],
        )

        assert stats["superseded_count"] == 1
        assert MemoryRepository().get(db, old.id).status == "superseded"
        text = store.core_path_for(identity_id).read_text(encoding="utf-8")
        assert "用户喜欢咖啡" not in text
        assert "用户已戒咖啡" in text


def test_goal_promotion_preserves_last_evidence_time(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        candidate = _candidate(db, store, identity_id, "goal", "用户准备三个月内学会 Rust")
        candidate.observed_at = utcnow() - timedelta(days=100)
        db.flush()
        stats = apply_consolidation(
            db, store, identity_id,
            [{
                "action": "add_core", "candidate_ids": [candidate.id],
                "type": "goal", "content": candidate.content, "importance": 7,
            }],
        )
        core = MemoryRepository().get(db, stats["core_ids"][0])
        assert core.last_evidence_at == candidate.observed_at
        assert needs_confirmation(core)


def test_apply_ignores_candidates(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        candidate = _candidate(db, store, identity_id, "fact", "今天聊了天气")
        db.commit()

        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [{"action": "ignore", "candidate_ids": [candidate.id]}],
        )

        assert stats["skipped_count"] == 1
        assert MemoryRepository().get(db, candidate.id).promotion_status == "deferred"
        assert MemoryRepository().list_owned(db, identity_id, tier="core") == []


def test_new_independent_observation_reopens_deferred_candidate(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        first_conversation = ConversationRepository().create(
            db, title="one", channel="local", identity_id=identity_id
        )
        second_conversation = ConversationRepository().create(
            db, title="two", channel="local", identity_id=identity_id
        )
        first_message = models.Message(
            id="first-message", conversation_id=first_conversation.id,
            role="user", content="我正在学习 Rust",
        )
        second_message = models.Message(
            id="second-message", conversation_id=second_conversation.id,
            role="user", content="我继续学习 Rust",
        )
        db.add_all([first_message, second_message])
        deferred = _candidate(db, store, identity_id, "goal", "用户正在学习 Rust")
        deferred.promotion_status = "deferred"
        deferred.source_message_id = first_message.id
        deferred.conversation_id = first_conversation.id
        fresh = _candidate(db, store, identity_id, "goal", "用户继续学习 Rust")
        fresh.source_message_id = second_message.id
        fresh.conversation_id = second_conversation.id
        db.flush()

        MemoryManager(store)._reopen_related_candidates(
            db, identity_id, fresh, {"type": "goal", "content": fresh.content}
        )

        assert deferred.promotion_status == "pending"


def test_apply_rejects_invalid_candidate(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "add_core",
                    "candidate_ids": ["nonexistent"],
                    "type": "preference",
                    "content": "不该写入",
                }
            ],
        )
        assert stats["promoted_count"] == 0
        assert MemoryRepository().list_owned(db, identity_id, tier="core") == []


def test_threshold_not_met_for_few_fresh_candidates():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    class Fake:
        pass

    candidates = []
    for _ in range(3):
        item = Fake()
        item.observed_at = now
        item.created_at = now
        candidates.append(item)
    assert ConsolidationProcessor._threshold_met(candidates) is False


def test_eligibility_requires_score_recall_count_and_distinct_queries(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    processor = ConsolidationProcessor(factory, store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        first_conversation = ConversationRepository().create(
            db, title="first", channel="local", identity_id=identity_id
        )
        first = _candidate(db, store, identity_id, "preference", "用户不喝咖啡")
        first.conversation_id = first_conversation.id
        path = store.daily_path(identity_id=identity_id)
        first_entry = store.append(path, first.content, meta={"type": first.type})
        first.file_path = store.relative_path(path)
        first.entry_key = first_entry.id
        first.content_hash = first_entry.hash
        db.commit()

        assert processor._eligible(db, identity_id, [first]) == []

        second_conversation = ConversationRepository().create(
            db, title="second", channel="local", identity_id=identity_id
        )
        second = _candidate(db, store, identity_id, "preference", "用户不喝含咖啡因饮品")
        second.conversation_id = second_conversation.id
        second_entry = store.append(path, second.content, meta={"type": second.type})
        second.file_path = store.relative_path(path)
        second.entry_key = second_entry.id
        second.content_hash = second_entry.hash
        db.commit()

        assert processor._eligible(db, identity_id, [first, second]) == []
        for query_hash in ("one", "two", "three"):
            db.add(MemoryRecallEvent(
                id=str(uuid4()), memory_id=first.id, identity_id=identity_id,
                query_hash=query_hash, score=1.0, recall_mode="deep",
            ))
        db.flush()
        assert [item.id for item in processor._eligible(db, identity_id, [first, second])] == [first.id]
        assert processor._promotion_score(db, identity_id, first, [first, second])["score"] >= 0.75


def test_run_sweep_promotes_end_to_end(tmp_path, monkeypatch):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="source", channel="local", identity_id=identity_id
        )
        candidate = _candidate(db, store, identity_id, "preference", "下午不再喝咖啡")
        path = store.daily_path(identity_id=identity_id)
        entry = store.append(path, candidate.content, meta={"type": candidate.type})
        candidate.trust = "owner"
        candidate.conversation_id = conversation.id
        candidate.file_path = store.relative_path(path)
        candidate.entry_key = entry.id
        candidate.content_hash = entry.hash
        candidate_id = candidate.id
        for query_hash in ("one", "two", "three"):
            db.add(MemoryRecallEvent(
                id=str(uuid4()), memory_id=candidate.id, identity_id=identity_id,
                query_hash=query_hash, score=1.0, recall_mode="deep",
            ))
        db.commit()

    class FakeClient(AIProvider):
        def __init__(self):
            super().__init__("fake")

        async def chat(self, messages, tools=None, stream=False, **kwargs):
            return LLMResponse(
                content=json.dumps(
                    [
                        {
                            "action": "add_core",
                            "candidate_ids": [candidate_id],
                            "type": "preference",
                            "content": "不向用户推荐咖啡",
                            "importance": 8,
                        }
                    ],
                    ensure_ascii=False,
                )
            )

    class FakeRouter:
        def get_provider(self, _config):
            return FakeClient()

    monkeypatch.setattr(
        "zhiyu.application.consolidation_jobs.provider_router", FakeRouter()
    )

    result = asyncio.run(
        ConsolidationProcessor(factory, store).run_sweep(dry_run=False, force=True)
    )

    assert result["status"] == "ok"
    assert result["promoted_count"] == 1
    with factory() as db:
        cores = MemoryRepository().list_owned(db, identity_id, tier="core")
        assert [item.content for item in cores] == ["不向用户推荐咖啡"]
        fresh = MemoryRepository().get(db, candidate_id)
        assert fresh.promotion_status == "promoted"
