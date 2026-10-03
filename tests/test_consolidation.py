"""记忆巩固（dreaming sweep）测试。"""

import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.core.memory.consolidation import apply_consolidation, parse_consolidation
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _candidate(db, identity_id, type, content):
    return MemoryRepository().create(
        db,
        type=type,
        content=content,
        identity_id=identity_id,
        tier="episodic",
        trust="agent",
        source_kind="message",
        promotion_status="pending",
    )


def _core(db, store, identity_id, type, content):
    path = store.path_for(type)
    entry = store.append(path, content, meta={"type": type})
    return MemoryRepository().create(
        db,
        type=type,
        content=entry.content,
        identity_id=identity_id,
        tier="core",
        trust="agent",
        source_kind="consolidation",
        file_path=path.name,
        line_start=entry.line_start,
        line_end=entry.line_end,
        content_hash=entry.hash,
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
        a = _candidate(db, identity_id, "preference", "下午不再喝咖啡")
        b = _candidate(db, identity_id, "preference", "以后别推荐咖啡")
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
        assert "不向用户推荐咖啡" in (tmp_path / "USER.md").read_text(encoding="utf-8")


def test_apply_supersedes_old_core(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        old = _core(db, store, identity_id, "preference", "用户喜欢咖啡")
        candidate = _candidate(db, identity_id, "preference", "用户戒咖啡了")
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
        text = (tmp_path / "USER.md").read_text(encoding="utf-8")
        assert "用户喜欢咖啡" not in text
        assert "用户已戒咖啡" in text


def test_apply_ignores_candidates(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        candidate = _candidate(db, identity_id, "fact", "今天聊了天气")
        db.commit()

        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [{"action": "ignore", "candidate_ids": [candidate.id]}],
        )

        assert stats["skipped_count"] == 1
        assert MemoryRepository().get(db, candidate.id).promotion_status == "rejected"
        assert MemoryRepository().list_owned(db, identity_id, tier="core") == []


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


def test_run_sweep_promotes_end_to_end(tmp_path, monkeypatch):
    factory = _database()
    with factory() as db:
        ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        identity_id = IdentityRepository().local(db).id
        candidate_id = _candidate(db, identity_id, "preference", "下午不再喝咖啡").id
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

    store = MemoryStore(tmp_path)
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
