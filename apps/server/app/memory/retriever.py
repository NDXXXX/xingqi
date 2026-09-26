"""Memory 检索：字符 bigram 重叠打分（MVP 无向量检索的轻量方案）。"""

from ..database.models import Memory


def _bigrams(text: str) -> set[str]:
    s = "".join(text.split()).lower()
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


def retrieve(query: str, memories: list[Memory], top_k: int = 5) -> list[Memory]:
    """按 query 与 content 的 bigram 重叠度排序，返回最相关的 top_k 条。"""
    q = _bigrams(query)
    if not q:
        return []
    scored: list[tuple[float, Memory]] = []
    for m in memories:
        overlap = len(q & _bigrams(m.content))
        if overlap == 0:
            continue
        score = overlap * (1 + (m.importance or 0.0))
        scored.append((score, m))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [m for _, m in scored[:top_k]]
