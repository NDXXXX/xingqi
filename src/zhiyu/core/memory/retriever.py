"""Memory 检索：归一化字符 bigram 重叠打分。"""

from math import sqrt

from zhiyu.infrastructure.database.models import Memory


def _bigrams(text: str) -> set[str]:
    s = "".join(text.split()).lower()
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


def retrieve(
    query: str,
    memories: list[Memory],
    top_k: int = 5,
    min_similarity: float = 0.15,
) -> list[Memory]:
    """按归一化 bigram 重叠度排序，返回达到门槛的 top_k 条。"""
    q = _bigrams(query)
    if not q:
        return []
    scored: list[tuple[float, Memory]] = []
    for m in memories:
        content = _bigrams(m.content)
        if not content:
            continue
        similarity = len(q & content) / sqrt(len(q) * len(content))
        if similarity < min_similarity:
            continue
        score = similarity * (1 + (m.importance or 0.0))
        scored.append((score, m))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [m for _, m in scored[:top_k]]
