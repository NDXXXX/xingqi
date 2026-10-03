"""生产召回链路的中文改写、硬负例、时态、深召回与降级测试。"""

import asyncio
import time

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.agent.context import with_agent_context
from zhiyu.core.memory.deep_recall import deep_recall
from zhiyu.core.memory.retriever import (
    build_query_plan,
    hybrid_rank,
    hybrid_rank_async,
)
from zhiyu.core.providers.embedding import save_config
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import MemoryRecallEvent
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


NATURAL_REWRITES = (
    ("早上锻炼怎么安排", "用户习惯晨跑"),
    ("给我推荐不含肉的晚餐", "用户偏好素食饮食"),
    ("接着做那个桌面助手", "用户正在开发知语个人 AI 助手"),
    ("我对象最近怎么样", "李梅是用户的女朋友"),
    ("别给我太啰嗦", "用户喜欢简洁回答"),
    ("搬家前我住哪儿", "用户曾居住在北京"),
)

HARD_NEGATIVES = (
    "用户习惯晚上散步",
    "用户周末去游泳",
    "用户在研究跑步机参数",
    "用户为朋友安排健身计划",
    "用户喜欢川菜",
    "用户对晚餐没有固定时间",
    "用户收藏了牛排餐厅",
    "用户最近在学习营养学",
    "用户正在开发移动端记账应用",
    "用户维护一个桌面壁纸仓库",
    "用户计划购买新的显示器",
    "用户的服务端使用 Rust",
    "王强是用户的同事",
    "李明是用户的大学同学",
    "用户最近联系了家人",
    "用户准备参加朋友的婚礼",
    "用户喜欢完整的技术文档",
    "用户写文章时会详细展开",
    "用户希望代码注释足够清楚",
    "用户讨厌含糊的结论",
    "用户去北京参加过会议",
    "用户计划到上海旅行",
    "用户收藏了杭州的酒店",
    "用户关注城市通勤时间",
    "用户喜欢乌龙茶",
    "用户不在下午喝饮料",
    "用户使用 Linux 工作站",
    "用户每周整理一次任务",
    "用户正在读一本历史小说",
    "用户对摄影器材感兴趣",
)


def test_natural_chinese_rewrites_rank_target_first_without_embeddings():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        repo = MemoryRepository()
        targets = {
            content: repo.create(
                db,
                type="fact",
                content=content,
                identity_id=identity_id,
                tier="core",
            )
            for _query, content in NATURAL_REWRITES
        }
        for content in HARD_NEGATIVES:
            repo.create(db, type="fact", content=content, identity_id=identity_id, tier="core")
        db.commit()
        memories = repo.list_owned(db, identity_id, tier="core")

        for query, expected in NATURAL_REWRITES:
            trace = hybrid_rank(db, query, memories, top_k=6)
            assert trace.selected, query
            assert trace.selected[0].memory.id == targets[expected].id, query


def test_unrelated_query_returns_empty_instead_of_filling_top_k():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        repo = MemoryRepository()
        for content in ("用户喜欢咖啡", "用户在学 Rust", "用户住在北京"):
            repo.create(db, type="fact", content=content, identity_id=identity_id)
        db.commit()
        trace = hybrid_rank(db, "今天的海浪高度是多少", repo.list_owned(db, identity_id))
        assert trace.candidates == []
        assert trace.selected == []


def test_query_builder_uses_recent_user_context_for_reference():
    plan = build_query_plan(
        "接着做那个项目",
        history=[
            {"role": "user", "content": "我们刚才在讨论知语桌面助手"},
            {"role": "assistant", "content": "好"},
        ],
    )
    assert any("知语桌面助手" in variant for variant in plan.variants)
    assert plan.recall_intent is True


def test_rrf_result_is_deterministic_and_channels_are_separate():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        repo = MemoryRepository()
        target = repo.create(
            db,
            type="project",
            content="用户正在开发知语个人 AI 助手",
            identity_id=identity_id,
            trigger_text="知语,桌面助手",
        )
        repo.create(
            db,
            type="project",
            content="用户正在开发手机应用",
            identity_id=identity_id,
        )
        db.commit()
        memories = repo.list_owned(db, identity_id)
        first = hybrid_rank(db, "继续知语桌面助手", memories)
        second = hybrid_rank(db, "继续知语桌面助手", memories)
        assert [item.memory.id for item in first.selected] == [
            item.memory.id for item in second.selected
        ]
        ranked = next(item for item in first.candidates if item.memory.id == target.id)
        assert {"exact", "trigger", "lexical"} <= set(ranked.channels)


def test_current_query_filters_superseded_historical_observation():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        repo = MemoryRepository()
        current = repo.create(
            db,
            type="fact",
            content="用户现在住在上海",
            identity_id=identity_id,
            tier="core",
            supersession_key="residence",
        )
        historical = repo.create(
            db,
            type="fact",
            content="用户曾居住在北京",
            identity_id=identity_id,
            tier="episodic",
            supersession_key="residence",
        )
        db.commit()
        trace = hybrid_rank(db, "我现在住在哪里", repo.list_owned(db, identity_id))
        assert [item.memory.id for item in trace.selected] == [current.id]
        filtered = next(item for item in trace.candidates if item.memory.id == historical.id)
        assert filtered.filtered_reason == "current_core_overrides_history"


def test_episodic_memory_is_injected_as_historical_evidence():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="chat", channel="local", identity_id=identity_id
        )
        episodic = MemoryRepository().create(
            db,
            type="goal",
            content="用户正在学习 Rust",
            identity_id=identity_id,
            tier="episodic",
            promotion_status="pending",
        )
        db.commit()
        result = with_agent_context(
            db,
            conversation,
            "Rust 学得怎么样了",
            [{"role": "user", "content": "Rust 学得怎么样了"}],
        )
        assert "[历史证据] 用户正在学习 Rust" in result[0]["content"]
        events = list(
            db.scalars(
                select(MemoryRecallEvent).where(MemoryRecallEvent.memory_id == episodic.id)
            )
        )
        assert len(events) == 1
        assert events[0].recall_mode == "search"


def test_unrelated_core_does_not_block_deep_recall():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        old = ConversationRepository().create(
            db, title="old", channel="local", identity_id=identity_id
        )
        MessageRepository().create(
            db,
            conversation_id=old.id,
            role="user",
            content="我决定用 Rust 重写同步模块",
        )
        current = ConversationRepository().create(
            db, title="current", channel="local", identity_id=identity_id
        )
        MemoryRepository().create(
            db, type="fact", content="用户喜欢咖啡", identity_id=identity_id
        )
        db.commit()
        result = with_agent_context(
            db,
            current,
            "我上次说的 Rust 决定是什么",
            [{"role": "user", "content": "我上次说的 Rust 决定是什么"}],
        )
        assert "Rust 重写同步模块" in result[0]["content"]
        assert "用户喜欢咖啡" not in result[0]["content"]


def test_deep_recall_reads_early_current_conversation_with_window():
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        conversation = ConversationRepository().create(
            db, title="long", channel="local", identity_id=identity_id
        )
        MessageRepository().create(
            db, conversation_id=conversation.id, role="user", content="旧项目代号叫星桥"
        )
        MessageRepository().create(
            db, conversation_id=conversation.id, role="assistant", content="我记下了这个代号"
        )
        for index in range(10):
            MessageRepository().create(
                db,
                conversation_id=conversation.id,
                role="user" if index % 2 == 0 else "assistant",
                content=f"中间消息 {index}",
            )
        result = deep_recall(
            db,
            identity_id,
            "以前那个星桥项目",
            current_conversation_id=conversation.id,
        )
        assert result is not None
        assert "旧项目代号叫星桥" in result
        assert "我记下了这个代号" in result


async def test_embedding_timeout_falls_back_to_lexical(monkeypatch):
    factory = _database()
    with factory() as db:
        identity_id = IdentityRepository().local(db).id
        target = MemoryRepository().create(
            db, type="fact", content="用户喜欢咖啡", identity_id=identity_id
        )
        save_config(
            db,
            base_url="https://embedding.invalid/v1",
            model="slow-model",
            api_key_ref="env:TEST_EMBEDDING_KEY",
        )
        db.commit()
        monkeypatch.setenv("TEST_EMBEDDING_KEY", "test")

        async def slow_embed(*args, **kwargs):
            await asyncio.sleep(1)
            return [[1.0, 0.0]]

        monkeypatch.setattr("zhiyu.core.providers.embedding.embed_async", slow_embed)
        started = time.monotonic()
        trace = await hybrid_rank_async(
            db,
            "咖啡",
            [target],
            embedding_timeout=0.01,
        )
        elapsed = time.monotonic() - started
        assert elapsed < 0.2
        assert trace.selected[0].memory.id == target.id
        assert "vector" not in trace.selected[0].channels
