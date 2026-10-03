"""Memory 检索：混合向量（embedding）与词法（字符 bigram）打分，MMR 去重。"""

from math import sqrt

from zhiyu.core.providers.embedding import embed_text, load_vectors
from zhiyu.infrastructure.database.models import Memory


def _bigrams(text: str) -> set[str]:
    s = "".join(text.split()).lower()
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _lexical_similarity(query: str, content: str) -> float:
    q = _bigrams(query)
    c = _bigrams(content)
    if not q or not c:
        return 0.0
    return len(q & c) / sqrt(len(q) * len(c))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve(
    query: str,
    memories: list[Memory],
    top_k: int = 5,
    min_similarity: float = 0.15,
) -> list[Memory]:
    """纯词法 bigram 检索（无 embedding 时的降级路径）。"""
    scored: list[tuple[float, Memory]] = []
    for memory in memories:
        similarity = _lexical_similarity(query, memory.content)
        if similarity < min_similarity:
            continue
        score = similarity * (1 + (memory.importance or 0.0))
        scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:top_k]]


def _mmr(scored: list[tuple[float, Memory]], top_k: int, lambda_: float = 0.7) -> list[tuple[float, Memory]]:
    """从按分数排序的候选中贪心选取，兼顾相关度与和已选结果的差异。"""
    remaining = list(scored)
    selected: list[tuple[float, Memory]] = []
    while remaining and len(selected) < top_k:
        best = max(
            remaining,
            key=lambda item: lambda_ * item[0]
            - (1 - lambda_)
            * max(
                (_lexical_similarity(item[1].content, chosen[1].content) for chosen in selected),
                default=0.0,
            ),
        )
        selected.append(best)
        remaining.remove(best)
    return selected


def hybrid_retrieve(
    db, query: str, memories: list[Memory], top_k: int = 5
) -> list[Memory]:
    """混合检索：向量 0.65 + 词法 0.35，乘 importance，再 MMR 去重。

    embedding 不可用时退化为纯词法（等价于 retrieve）。
    """
    if not memories:
        return []
    query_vec = None
    result = embed_text(db, query)
    if result is not None:
        query_vec = result[1]
    vectors = load_vectors(db, [memory.id for memory in memories])

    scored: list[tuple[float, Memory]] = []
    for memory in memories:
        lexical = _lexical_similarity(query, memory.content)
        vec = vectors.get(memory.id)
        vector_sim = _cosine(query_vec, vec) if (query_vec is not None and vec is not None) else 0.0
        if query_vec is not None and vec is not None:
            hybrid = 0.65 * vector_sim + 0.35 * lexical
        else:
            hybrid = lexical
        score = hybrid * (1.0 + (memory.importance or 0.0))
        scored.append((score, memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in _mmr(scored, top_k)]
