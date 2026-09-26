"""Memory 检索与提取测试。"""

from app.database.models import Memory
from app.memory.extractor import parse_candidates
from app.memory.manager import MemoryManager
from app.memory.retriever import retrieve


def _memory(content: str, importance: float = 0.5, type: str = "fact") -> Memory:
    return Memory(id="m", user_id=None, type=type, content=content, importance=importance)


def test_retrieve_ranks_relevant_first():
    memories = [
        _memory("用户在开发桌面 AI 项目"),
        _memory("用户喜欢喝咖啡"),
    ]
    result = retrieve("继续搞桌面 AI 项目", memories)
    assert result and result[0].content == "用户在开发桌面 AI 项目"


def test_retrieve_top_k():
    memories = [_memory("用户喜欢咖啡"), _memory("用户喜欢茶"), _memory("用户喜欢牛奶")]
    result = retrieve("你喜欢咖啡吗", memories, top_k=1)
    assert len(result) == 1
    assert result[0].content == "用户喜欢咖啡"


def test_retrieve_no_match():
    assert retrieve("今天天气如何", [_memory("用户喜欢咖啡")]) == []


def test_parse_candidates_with_fence():
    text = '```json\n[{"type": "preference", "content": "用户喜欢咖啡"}]\n```'
    assert parse_candidates(text) == [{"type": "preference", "content": "用户喜欢咖啡"}]


def test_parse_candidates_plain():
    assert parse_candidates('[{"type": "fact", "content": "用户在北京"}]') == [
        {"type": "fact", "content": "用户在北京"}
    ]


def test_parse_candidates_invalid():
    assert parse_candidates("没有可提取的内容") == []
    assert parse_candidates('[{"type": "unknown", "content": "x"}]') == []


def test_is_duplicate():
    existing = [_memory("用户喜欢咖啡")]
    assert MemoryManager._is_duplicate("用户喜欢咖啡", existing) is True
    assert MemoryManager._is_duplicate("喜欢咖啡", existing) is True
    assert MemoryManager._is_duplicate("用户喜欢茶", existing) is False
