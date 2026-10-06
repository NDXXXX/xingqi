"""身份 vault、稳定条目、崩溃恢复和来源遗忘的回归测试。"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from filelock import FileLock, Timeout
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.memories import MemoryService
from zhiyu.core.memory.consolidation import apply_consolidation
from zhiyu.core.memory.indexer import rebuild_index, sync_changed_index
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.mutations import FileMutationManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import (
    ForgottenConversation,
    MemoryEmbedding,
    MemoryMutation,
    MemorySource,
)
from zhiyu.infrastructure.database.repositories.conversation_repository import (
    ConversationRepository,
)
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository


def _database():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


class ObservationProvider(AIProvider):
    def __init__(self, observations):
        super().__init__(None)
        self.observations = observations

    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content=json.dumps(self.observations, ensure_ascii=False))


def test_rebuild_is_scoped_to_one_identity(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identities = IdentityRepository()
        local = identities.local(db)
        qq_a = identities.get_or_create(db, "qq", "10001")
        qq_b = identities.get_or_create(db, "qq", "10002")
        store.append(store.core_path, "旧全局文件不得导入", meta={"type": "fact"})
        store.append(store.core_path_for(local.id), "本地秘密", meta={"type": "fact"})
        store.append(store.core_path_for(qq_a.id), "QQ A 秘密", meta={"type": "fact"})
        store.append(store.core_path_for(qq_b.id), "QQ B 秘密", meta={"type": "fact"})

        for identity_id in (local.id, qq_a.id, qq_b.id):
            rebuild_index(db, store, identity_id)

        repo = MemoryRepository()
        assert {item.content for item in repo.list_owned(db, local.id)} == {"本地秘密"}
        assert {item.content for item in repo.list_owned(db, qq_a.id)} == {"QQ A 秘密"}
        assert {item.content for item in repo.list_owned(db, qq_b.id)} == {"QQ B 秘密"}


def test_daily_path_uses_shanghai_calendar_day(tmp_path):
    store = MemoryStore(tmp_path)
    utc_evening = datetime(2026, 10, 1, 16, 30, tzinfo=timezone.utc)
    assert store.daily_path(utc_evening, "local").name == "2026-10-02.md"
    assert store.daily_path(utc_evening.replace(tzinfo=None), "local").name == "2026-10-02.md"


def test_identity_cannot_escape_vault_root(tmp_path):
    store = MemoryStore(tmp_path)
    for identity_id in ("..", ".", "../other", "a/b"):
        try:
            store.vault_dir(identity_id)
        except ValueError:
            pass
        else:
            raise AssertionError(f"identity escaped vault root: {identity_id}")


def test_file_lock_timeout_does_not_wait_forever(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    path = store.core_path_for("local")
    path.parent.mkdir(parents=True)
    lock_path = path.parent / f".{path.name}.lock"
    monkeypatch.setattr("zhiyu.core.memory.store._LOCK_TIMEOUT_SECONDS", 0.01)

    with FileLock(str(lock_path)):
        with pytest.raises(Timeout):
            store.append(path, "不能无限等待", meta={"type": "fact"})


def test_atomic_replace_failure_preserves_original_file(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path)
    path = store.core_path_for("local")
    first = store.append(path, "原始内容", meta={"type": "fact"})
    original = path.read_text(encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("zhiyu.core.memory.store.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        store.replace_by_id(
            path,
            first.id,
            "不完整的新内容",
            {"id": first.id, "type": "fact"},
        )

    assert path.read_text(encoding="utf-8") == original
    assert list(path.parent.glob(".memory-*.tmp")) == []


def test_rebuild_uses_entry_ids_and_preserves_duplicate_content(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        first = store.append(path, "正文完全相同", meta={"type": "fact"})
        second = store.append(path, "正文完全相同", meta={"type": "fact"})
        rebuild_index(db, store, identity_id)

        active = MemoryRepository().list_owned(db, identity_id)
        assert len(active) == 2
        assert {item.entry_key for item in active} == {first.id, second.id}

        store.remove_by_id(path, first.id)
        rebuild_index(db, store, identity_id)
        all_rows = MemoryRepository().list_owned(db, identity_id, statuses=None)
        assert [(item.entry_key, item.status) for item in all_rows if item.status == "active"] == [
            (second.id, "active")
        ]
        assert next(item for item in all_rows if item.entry_key == first.id).status == "invalidated"


def test_rebuild_rejects_duplicate_stable_entry_id(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        store.append(path, "第一条", meta={"id": "duplicate-id", "type": "fact"})
        store.append(path, "第二条", meta={"id": "duplicate-id", "type": "fact"})
        try:
            rebuild_index(db, store, identity_id)
        except ValueError as exc:
            assert "重复 entry id" in str(exc)
        else:
            raise AssertionError("重复稳定 ID 不应被静默合并")


def test_deleting_whole_markdown_file_invalidates_its_index(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        store.append(path, "稍后会被整文件删除", meta={"type": "fact"})
        rebuild_index(db, store, identity_id)
        path.unlink()
        stats = rebuild_index(db, store, identity_id)
        assert stats["invalidated"] == 1
        rows = MemoryRepository().list_owned(db, identity_id, statuses=None)
        assert len(rows) == 1
        assert rows[0].status == "invalidated"


def test_external_edit_invalidates_stale_embedding(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        entry = store.append(path, "用户住在北京", meta={"type": "fact"})
        rebuild_index(db, store, identity_id)
        memory = MemoryRepository().list_owned(db, identity_id)[0]
        db.add(
            MemoryEmbedding(
                id=str(uuid4()),
                memory_id=memory.id,
                model="old-model",
                vector_json="[1.0, 0.0]",
            )
        )
        db.commit()

        store.replace_by_id(
            path,
            entry.id,
            "用户住在上海",
            {"id": entry.id, "type": "fact"},
        )
        rebuild_index(db, store, identity_id)

        assert db.scalars(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory.id)
        ).first() is None
        assert MemoryRepository().get(db, memory.id).content == "用户住在上海"


def test_completed_goal_is_not_resurrected_by_rebuild(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    goal = service.add(type="goal", content="完成记忆重构")
    service.complete(goal.id)

    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        rebuild_index(db, store, identity_id)
        row = MemoryRepository().get_owned(db, identity_id, goal.id)
        assert row.status == "completed"
        assert MemoryRepository().list_owned(db, identity_id) == []


def test_prepared_append_recovers_once_during_rebuild(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    manager = FileMutationManager(store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        mutation = manager._prepare(
            db,
            identity_id,
            "append",
            path,
            "recover-entry",
            {
                "content": "崩溃前准备写入的记忆",
                "meta": {"id": "recover-entry", "type": "fact"},
            },
        )
        assert mutation.status == "prepared"

    with factory() as db:
        first = rebuild_index(db, store, identity_id)
        second = rebuild_index(db, store, identity_id)
        rows = MemoryRepository().list_owned(db, identity_id)
        assert first["mutations_recovered"] == 1
        assert second["mutations_recovered"] == 0
        assert [item.content for item in rows] == ["崩溃前准备写入的记忆"]
        assert db.get(MemoryMutation, mutation.id).status == "completed"


def test_file_applied_orphan_is_indexed_and_completed(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    manager = FileMutationManager(store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        _entry, mutation = manager.append(
            db,
            identity_id,
            store.core_path_for(identity_id),
            "文件已经写入但索引尚未提交",
            meta={"type": "fact"},
        )
        mutation_id = mutation.id
        assert mutation.status == "file_applied"

    with factory() as db:
        stats = rebuild_index(db, store, identity_id)
        assert stats["mutations_completed"] == 1
        assert db.get(MemoryMutation, mutation_id).status == "completed"
        assert [item.content for item in MemoryRepository().list_owned(db, identity_id)] == [
            "文件已经写入但索引尚未提交"
        ]


def test_orphan_recovery_preserves_safe_source_context(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    manager = FileMutationManager(store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="source", channel="local", identity_id=identity_id
        )
        message = MessageRepository().create(
            db,
            conversation_id=conversation.id,
            role="user",
            content="我在学习 Rust",
        )
        manager.append(
            db,
            identity_id,
            store.daily_path(identity_id=identity_id),
            "用户在学习 Rust",
            meta={"type": "goal"},
            context={
                "origin": "automatic",
                "tier": "episodic",
                "trust": "agent",
                "source_kind": "message",
                "promotion_status": "pending",
                "source_message_id": message.id,
                "conversation_id": conversation.id,
            },
        )
        message_id = message.id

    with factory() as db:
        rebuild_index(db, store, identity_id)
        rows = MemoryRepository().list_owned(db, identity_id)
        assert len(rows) == 1
        assert rows[0].tier == "episodic"
        assert rows[0].trust == "agent"
        assert rows[0].origin == "automatic"
        assert rows[0].source_message_id == message_id
        assert MemoryRepository().has_source_action(db, identity_id, message_id)


def test_consolidation_orphan_is_not_elevated_to_manual_trust(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    manager = FileMutationManager(store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        daily = store.daily_path(identity_id=identity_id)
        source_entry = store.append(
            daily, "用户不喝咖啡", meta={"type": "preference"}
        )
        source = MemoryRepository().create(
            db,
            type="preference",
            content=source_entry.content,
            identity_id=identity_id,
            tier="episodic",
            trust="agent",
            promotion_status="pending",
            file_path=store.relative_path(daily),
            content_hash=source_entry.hash,
            entry_key=source_entry.id,
        )
        manager.append(
            db,
            identity_id,
            store.user_path_for(identity_id),
            "不向用户推荐咖啡",
            meta={"type": "preference"},
            context={
                "origin": "automatic",
                "tier": "core",
                "trust": "agent",
                "source_kind": "consolidation",
                "promotion_status": "none",
                "source_memory_ids": [source.id],
            },
        )
        source_id = source.id

    with factory() as db:
        rebuild_index(db, store, identity_id)
        core = MemoryRepository().list_owned(db, identity_id, tier="core")[0]
        assert core.origin == "automatic"
        assert core.trust == "agent"
        assert MemoryRepository().get(db, source_id).promoted_to_id == core.id
        assert db.scalars(
            select(MemorySource).where(MemorySource.memory_id == core.id)
        ).first() is not None


def test_external_edit_causes_mutation_conflict_without_overwrite(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    manager = FileMutationManager(store)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        mutation = manager._prepare(
            db,
            identity_id,
            "append",
            path,
            "pending-entry",
            {
                "content": "后台版本",
                "meta": {"id": "pending-entry", "type": "fact"},
            },
        )
        store.append(path, "用户手工编辑的版本", meta={"type": "fact"})
        assert manager.recover_prepared(db, identity_id) == 0
        db.refresh(mutation)
        assert mutation.status == "failed"
        assert "并发修改" in mutation.last_error
        text = path.read_text(encoding="utf-8")
        assert "用户手工编辑的版本" in text
        assert "后台版本" not in text


def test_remove_recovery_preserves_completed_lifecycle(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    summary = service.add(type="goal", content="完成恢复测试")
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        memory = MemoryRepository().get_owned(db, identity_id, summary.id)
        mutation = FileMutationManager(store).remove(
            db,
            identity_id,
            store.resolve_relative(memory.file_path),
            memory.entry_key,
            context={"lifecycle": "completed"},
        )
        mutation_id = mutation.id

    with factory() as db:
        stats = rebuild_index(db, store, identity_id)
        assert stats["lifecycle_recovered"] == 1
        assert MemoryRepository().get(db, summary.id).status == "completed"
        assert db.get(MemoryMutation, mutation_id).status == "completed"


def test_remove_recovery_can_finish_delete_and_tombstone(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    summary = service.add(type="fact", content="删除崩溃恢复测试")
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="forgotten", channel="local", identity_id=identity_id
        )
        memory = MemoryRepository().get_owned(db, identity_id, summary.id)
        FileMutationManager(store).remove(
            db,
            identity_id,
            store.resolve_relative(memory.file_path),
            memory.entry_key,
            context={
                "lifecycle": "delete",
                "forgotten_conversation_id": conversation.id,
            },
        )
        conversation_id = conversation.id

    with factory() as db:
        stats = rebuild_index(db, store, identity_id)
        assert stats["lifecycle_recovered"] == 1
        assert MemoryRepository().get(db, summary.id) is None
        assert db.scalars(
            select(ForgottenConversation).where(
                ForgottenConversation.identity_id == identity_id,
                ForgottenConversation.conversation_id == conversation_id,
            )
        ).first() is not None


def _candidate(db, identity_id, conversation_id, content):
    return MemoryRepository().create(
        db,
        type="preference",
        content=content,
        identity_id=identity_id,
        tier="episodic",
        trust="agent",
        source_kind="message",
        promotion_status="pending",
        conversation_id=conversation_id,
    )


def test_forgetting_removes_core_only_after_last_source(tmp_path):
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
        first = _candidate(db, identity_id, first_conversation.id, "用户不喝咖啡")
        second = _candidate(db, identity_id, second_conversation.id, "用户不喝含咖啡因饮品")
        db.commit()
        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "add_core",
                    "candidate_ids": [first.id, second.id],
                    "type": "preference",
                    "content": "不向用户推荐含咖啡因饮品",
                    "importance": 8,
                }
            ],
        )
        core_id = stats["core_ids"][0]
        first_conversation_id = first_conversation.id
        second_conversation_id = second_conversation.id

    service = MemoryService(factory, store=store)
    first_plan = service.plan_forget(conversation_id=first_conversation_id)
    assert next(
        item for item in first_plan["entries"] if item["id"] == core_id
    )["action"] == "retain"
    service.forget_conversation(first_conversation_id)
    with factory() as db:
        assert MemoryRepository().get_owned(db, identity_id, core_id) is not None
        assert db.scalars(
            select(MemorySource).where(MemorySource.memory_id == core_id)
        ).all()

    second_plan = service.plan_forget(conversation_id=second_conversation_id)
    assert next(
        item for item in second_plan["entries"] if item["id"] == core_id
    )["action"] == "delete"
    service.forget_conversation(second_conversation_id)
    with factory() as db:
        assert MemoryRepository().get_owned(db, identity_id, core_id) is None


def test_forgetting_single_source_removes_orphaned_automatic_core(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="one", channel="local", identity_id=identity_id
        )
        candidate = _candidate(
            db, identity_id, conversation.id, "用户不喝咖啡"
        )
        db.commit()
        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "add_core",
                    "candidate_ids": [candidate.id],
                    "type": "preference",
                    "content": "不向用户推荐咖啡",
                    "importance": 8,
                }
            ],
        )
        core_id = stats["core_ids"][0]
        candidate_id = candidate.id

    service = MemoryService(factory, store=store)
    plan = service.plan_forget(memory_id=candidate_id)
    assert {item["id"] for item in plan["entries"]} == {candidate_id, core_id}
    service.forget(candidate_id)

    with factory() as db:
        assert MemoryRepository().get_owned(db, identity_id, candidate_id) is None
        assert MemoryRepository().get_owned(db, identity_id, core_id) is None


def test_forget_recovery_finishes_orphaned_core_cascade(tmp_path, monkeypatch):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="crash", channel="local", identity_id=identity_id
        )
        path = store.daily_path(identity_id=identity_id)
        entry = store.append(
            path, "用户不喝咖啡", meta={"type": "preference"}
        )
        candidate = MemoryRepository().create(
            db,
            type="preference",
            content=entry.content,
            identity_id=identity_id,
            tier="episodic",
            trust="agent",
            source_kind="message",
            promotion_status="pending",
            conversation_id=conversation.id,
            file_path=store.relative_path(path),
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        db.commit()
        stats = apply_consolidation(
            db,
            store,
            identity_id,
            [
                {
                    "action": "add_core",
                    "candidate_ids": [candidate.id],
                    "type": "preference",
                    "content": "不向用户推荐咖啡",
                    "importance": 8,
                }
            ],
        )
        core_id = stats["core_ids"][0]
        candidate_id = candidate.id
        conversation_id = conversation.id

    service = MemoryService(factory, store=store)
    lifecycle = service._lifecycle
    remove_from_file = lifecycle._remove_from_file
    calls = 0

    def crash_before_second_remove(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated crash")
        return remove_from_file(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "_remove_from_file", crash_before_second_remove)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.forget_conversation(conversation_id)

    with factory() as db:
        recovery = rebuild_index(db, store, identity_id)
        assert recovery["lifecycle_recovered"] == 2
        assert MemoryRepository().get_owned(db, identity_id, candidate_id) is None
        assert MemoryRepository().get_owned(db, identity_id, core_id) is None
        assert db.scalars(
            select(ForgottenConversation).where(
                ForgottenConversation.identity_id == identity_id,
                ForgottenConversation.conversation_id == conversation_id,
            )
        ).first() is not None
        assert "不向用户推荐咖啡" not in store.user_path_for(
            identity_id
        ).read_text(encoding="utf-8")


async def test_forgotten_conversation_cannot_be_reingested(tmp_path):
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="forgotten", channel="local", identity_id=identity_id
        )
        message = MessageRepository().create(
            db,
            conversation_id=conversation.id,
            role="user",
            content="我在学习 Rust",
        )
        db.add(
            ForgottenConversation(
                id="forgotten-row",
                identity_id=identity_id,
                conversation_id=conversation.id,
            )
        )
        db.commit()

        changed = await MemoryManager(store=MemoryStore(tmp_path)).extract_and_save(
            db,
            ObservationProvider(
                [{"type": "goal", "content": "用户在学习 Rust", "evidence": "我在学习 Rust"}]
            ),
            "test",
            "我在学习 Rust",
            "好的",
            identity_id,
            user_message_id=message.id,
        )
        assert changed == []
        assert MemoryRepository().list_owned(db, identity_id) == []


def test_rebuild_prunes_tombstoned_source_instead_of_backfilling(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="forgotten", channel="local", identity_id=identity_id
        )
        path = store.daily_path(identity_id=identity_id)
        entry = store.append(path, "不应复活的观察", meta={"type": "fact"})
        memory = MemoryRepository().create(
            db,
            type="fact",
            content=entry.content,
            identity_id=identity_id,
            tier="episodic",
            conversation_id=conversation.id,
            file_path=store.relative_path(path),
            content_hash=entry.hash,
            entry_key=entry.id,
        )
        db.add(
            ForgottenConversation(
                id="forgotten-index-row",
                identity_id=identity_id,
                conversation_id=conversation.id,
            )
        )
        db.commit()

        stats = rebuild_index(db, store, identity_id)
        assert stats["forgotten_pruned"] == 1
        assert MemoryRepository().get(db, memory.id).status == "forgotten"
        assert "不应复活的观察" not in path.read_text(encoding="utf-8")
        assert MemoryRepository().list_owned(db, identity_id) == []


async def test_explicit_single_target_correction_updates_core_immediately(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    service = MemoryService(factory, store=store)
    old = service.add(type="preference", content="用户喜欢咖啡")
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="correction", channel="local", identity_id=identity_id
        )
        message = MessageRepository().create(
            db,
            conversation_id=conversation.id,
            role="user",
            content="我不喝咖啡了",
        )
        changed = await MemoryManager(store=store).extract_and_save(
            db,
            ObservationProvider(
                [{"type": "preference", "content": "用户不喝咖啡", "evidence": "我不喝咖啡了"}]
            ),
            "test",
            "我不喝咖啡了",
            "知道了",
            identity_id,
            user_message_id=message.id,
        )
        assert len(changed) == 1
        assert changed[0].tier == "core"
        assert changed[0].supersedes_id == old.id
        assert MemoryRepository().get_owned(db, identity_id, old.id).status == "superseded"
        text = store.user_path_for(identity_id).read_text(encoding="utf-8")
        assert "用户喜欢咖啡" not in text
        assert "用户不喝咖啡" in text


async def test_explicit_remember_writes_core_and_secret_is_ignored(tmp_path):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="remember", channel="local", identity_id=identity_id
        )
        message = MessageRepository().create(
            db, conversation_id=conversation.id, role="user",
            content="记住我喜欢手冲咖啡",
        )
        manager = MemoryManager(store=store)
        written = await manager.extract_and_save(
            db,
            ObservationProvider([{
                "type": "preference", "content": "用户喜欢手冲咖啡",
                "evidence": "记住我喜欢手冲咖啡",
            }]),
            "test", message.content, "好的", identity_id,
            user_message_id=message.id,
        )
        assert len(written) == 1
        assert written[0].tier == "core"
        assert written[0].source_message_id == message.id

        secret = await manager.extract_and_save(
            db,
            ObservationProvider([{
                "type": "fact", "content": "用户的 API Key 是 sk-1234567890abcdefghijkl",
                "evidence": "我的 API Key 是 sk-1234567890abcdefghijkl",
            }]),
            "test", "记住我的 API Key 是 sk-1234567890abcdefghijkl", "好的", identity_id,
        )
        assert secret == []


def test_trigger_is_regenerated_on_manual_edit(tmp_path):
    factory = _database()
    service = MemoryService(factory, store=MemoryStore(tmp_path))
    first = service.add(type="preference", content="用户喜欢咖啡")
    second = service.edit(first.id, content="用户喜欢乌龙茶")
    with factory() as db:
        old = db.get(models.Memory, first.id)
        new = db.get(models.Memory, second.id)
        assert "咖啡" in old.trigger_text
        assert "乌龙茶" in new.trigger_text
        assert old.status == "superseded"


def test_changed_index_skips_unchanged_files_and_updates_only_edited_file(tmp_path, monkeypatch):
    factory = _database()
    store = MemoryStore(tmp_path)
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        store.append(path, "用户喜欢咖啡", meta={"type": "preference", "id": "coffee"})
        first = sync_changed_index(db, store, identity_id)
        assert first["files_changed"] == 1
        assert first["created"] == 1

        original_read = store.read_entries
        reads = []

        def counted_read(file_path):
            reads.append(file_path)
            return original_read(file_path)

        monkeypatch.setattr(store, "read_entries", counted_read)
        unchanged = sync_changed_index(db, store, identity_id)
        assert unchanged["files_changed"] == 0
        assert reads == []

        monkeypatch.setattr(store, "read_entries", original_read)
        store.append(path, "用户喜欢乌龙茶", meta={"type": "preference", "id": "tea"})
        edited = sync_changed_index(db, store, identity_id)
        assert edited["files_changed"] == 1
        assert edited["created"] == 1
        assert {item.content for item in MemoryRepository().list_owned(db, identity_id)} == {
            "用户喜欢咖啡", "用户喜欢乌龙茶"
        }

        store.replace_by_id(
            path, "coffee", "用户喜欢浓缩咖啡",
            {"type": "preference", "id": "coffee"},
        )
        sync_changed_index(db, store, identity_id)
        edited_memory = next(
            item for item in MemoryRepository().list_owned(db, identity_id)
            if item.entry_key == "coffee"
        )
        assert edited_memory.content == "用户喜欢浓缩咖啡"
        assert edited_memory.trust == "imported"
        assert edited_memory.source_kind == "import"
        assert edited_memory.source_message_id is None
