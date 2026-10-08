"""中文友好的多路记忆召回：查询构建、候选生成、RRF、时态与 MMR。"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError

from zhiyu.core.providers.embedding import embed_text, embed_text_async, load_vectors
from zhiyu.infrastructure.database.models import Memory, utcnow


_RECALL_RE = re.compile(r"上次|之前|以前|记得|说过|聊过|提到|那天|上回|当时|曾经|搬家前")
_CURRENT_RE = re.compile(r"现在|目前|以后|最近|当前")
_PAST_RE = re.compile(r"以前|之前|当时|曾经|搬家前|过去")
_SELF_NAME_RE = re.compile(r"你.{0,8}(?:叫什么|叫啥|名字|称呼)|助手.{0,8}(?:叫什么|名字|称呼)|我给你起名")
_REFERENCE_RE = re.compile(
    r"那个|这个|那里|那儿|这里|她|他|它|上次的|以前那个|照旧|什么人|哪个"
)

# 受控同义组只用于生成查询候选，不产生新的用户事实。
_ALIASES: tuple[tuple[str, ...], ...] = (
    ("早上", "早晨", "清晨"),
    ("锻炼", "运动", "跑步", "晨跑", "路跑", "有氧"),
    ("不含肉", "不吃肉", "素食", "无肉", "植物性饮食", "plant-based"),
    ("对象", "伴侣", "女朋友", "男朋友"),
    ("啰嗦", "简洁回答", "精简", "收短", "短一点"),
    ("详细", "展开", "完整解释", "讲清楚"),
    ("住哪儿", "住哪里", "居住", "住在", "定居", "居住地"),
    ("桌面助手", "个人 AI 助手", "AI 助手", "知语", "智能助理", "桌面助理"),
    ("本地", "离线"),
    ("接着做", "继续", "跟进"),
    ("项目", "工程"),
    ("咖啡因", "咖啡", "含咖啡因饮品", "拿铁", "美式"),
    ("网站", "站点", "个人网站", "个人站点", "主页", "homepage", "线上页面"),
    ("妈妈", "母亲", "老妈"),
    ("生日", "过生日"),
    ("接触猫", "猫过敏", "碰到猫", "喵星人", "打喷嚏"),
    ("现在", "目前", "当前"),
    ("以前", "之前", "过去", "曾经", "搬家前"),
    ("忌口", "不吃", "不要出现"),
    ("香菜", "芫荽"),
    ("MCP", "Model Context Protocol", "模型上下文协议", "协议接入"),
    ("日语 N1", "N1", "JLPT", "最高级日语考试", "日语考试"),
    ("杭州", "杭城", "钱塘"),
    ("姐姐", "姐妹", "家人"),
    ("游戏公司", "游戏行业", "做游戏的单位"),
    ("合伙人", "创业搭档", "一起创业", "合作关系"),
    ("英语", "英文"),
    ("科幻", "SF", "未来世界题材"),
    ("游泳", "泳池", "水上运动", "下水训练"),
    ("北京", "帝都"),
    ("Python", "Py", "蟒蛇语言"),
    ("出差", "差旅", "商务旅行", "办事"),
)

_GENERIC_ALIAS_TERMS = {
    "继续",
    "跟进",
    "项目",
    "工程",
    "对象",
    "伴侣",
    "女朋友",
    "男朋友",
    "居住",
    "住在",
}


@dataclass(slots=True)
class QueryPlan:
    original: str
    normalized: str
    variants: list[str]
    temporal_intent: str
    recall_intent: bool


@dataclass(slots=True)
class RankedMemory:
    memory: Memory
    rrf_score: float
    confidence: float
    channels: dict[str, float] = field(default_factory=dict)
    filtered_reason: str | None = None


@dataclass(slots=True)
class RecallTrace:
    plan: QueryPlan
    candidates: list[RankedMemory]
    selected: list[RankedMemory]


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).lower().strip()
    value = re.sub(r"[，。！？、；：,.!?;:()（）\[\]{}]+", " ", value)
    return " ".join(value.split())


def derive_trigger_text(content: str) -> str | None:
    """从核心正文确定性生成少量高精度触发词，不引入正文外事实。"""
    normalized = normalize_text(content)
    candidates: list[str] = []

    compact = _compact(normalized)
    trimmed = re.sub(
        r"^(用户|我)(目前|现在|曾经|以前|正在|已经|已|每天|通常|习惯|偏好|喜欢|希望|计划)?",
        "",
        compact,
    )
    if 2 <= len(trimmed) <= 24:
        candidates.append(trimmed)

    for group in _ALIASES:
        if any(term.lower() in normalized for term in group):
            candidates.extend(term for term in group if term.lower() in normalized)

    candidates.extend(re.findall(r"[a-z][a-z0-9.+_-]{1,31}", normalized))
    seen: set[str] = set()
    kept: list[str] = []
    for candidate in candidates:
        value = normalize_text(candidate)
        if len(value) < 2 or len(value) > 32 or value in seen:
            continue
        seen.add(value)
        kept.append(value)
        if len(kept) == 5:
            break
    return ",".join(kept) or None


def build_query_plan(query: str, history: list[dict] | None = None) -> QueryPlan:
    normalized = normalize_text(query)
    variants = [normalized] if normalized else []
    seen = set(variants)
    for group in _ALIASES:
        matching = [term for term in group if term.lower() in normalized]
        for source in matching:
            for target in group:
                variant = normalize_text(normalized.replace(source.lower(), target.lower()))
                if variant and variant not in seen:
                    variants.append(variant)
                    seen.add(variant)
                anchor = normalize_text(target)
                if anchor not in _GENERIC_ALIAS_TERMS and anchor not in seen:
                    variants.append(anchor)
                    seen.add(anchor)
                if len(variants) >= 24:
                    break
            if len(variants) >= 24:
                break
        if len(variants) >= 24:
            break

    if _SELF_NAME_RE.search(normalized):
        for variant in ("给助手起名", "助手名字"):
            if variant not in seen:
                variants.append(variant)
                seen.add(variant)

    if _REFERENCE_RE.search(normalized) and history:
        for message in reversed(history[-4:]):
            if message.get("role") != "user":
                continue
            context = normalize_text(str(message.get("content", "")))
            if context and context != normalized:
                if context not in seen:
                    variants.append(context)
                    seen.add(context)
                variant = f"{normalized} {context}"
                if variant not in seen:
                    variants.append(variant)
                break

    temporal = "past" if _PAST_RE.search(normalized) else "current" if _CURRENT_RE.search(normalized) else "any"
    return QueryPlan(
        original=query,
        normalized=normalized,
        variants=variants[:24],
        temporal_intent=temporal,
        recall_intent=bool(_RECALL_RE.search(normalized) or _REFERENCE_RE.search(normalized)),
    )


def _compact(text: str) -> str:
    return "".join(normalize_text(text).split())


def _ngrams(text: str, size: int) -> set[str]:
    return _ngrams_compact(_compact(text), size)


def _ngrams_compact(compact: str, size: int) -> set[str]:
    if not compact:
        return set()
    if len(compact) <= size:
        return {compact}
    return {compact[i : i + size] for i in range(len(compact) - size + 1)}


def _bigrams(text: str) -> set[str]:
    return _ngrams(text, 2)


def _set_cosine(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def _lexical_similarity(query: str, content: str) -> float:
    # Trigrams improve precision on longer Chinese phrases; bigrams preserve recall
    # for short names and mixed Chinese/English input.
    return max(
        _set_cosine(_ngrams(query, 2), _ngrams(content, 2)),
        _set_cosine(_ngrams(query, 3), _ngrams(content, 3)),
    )


def _lexical_similarity_features(
    query_features: list[tuple[set[str], set[str]]],
    content_features: tuple[set[str], set[str]],
) -> float:
    content_bigrams, content_trigrams = content_features
    return max(
        (
            max(
                _set_cosine(query_bigrams, content_bigrams),
                _set_cosine(query_trigrams, content_trigrams),
            )
            for query_bigrams, query_trigrams in query_features
        ),
        default=0.0,
    )


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def fts_ranked_ids(db, query: str, identity_ids: set[str], limit: int = 50) -> list[str]:
    """BM25 候选；旧测试库或未迁移数据库继续使用现有词法检索。"""
    if not identity_ids or db.get_bind().dialect.name != "sqlite":
        return []
    plan = build_query_plan(query)
    terms: list[str] = []
    seen: set[str] = set()
    for variant in plan.variants:
        compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", _compact(variant))
        for term in sorted(_ngrams_compact(compact, 3)):
            if len(term) != 3 or term in seen:
                continue
            seen.add(term)
            terms.append(term)
            if len(terms) >= 48:
                break
        if len(terms) >= 48:
            break
    if not terms:
        return []
    expression = " OR ".join('"' + term + '"' for term in terms)
    statement = text(
        "SELECT memories.id FROM memory_fts "
        "JOIN memories ON memories.rowid = memory_fts.rowid "
        "WHERE memory_fts MATCH :expression "
        "AND memories.identity_id IN :identities AND memories.status = 'active' "
        "ORDER BY bm25(memory_fts) LIMIT :limit"
    ).bindparams(bindparam("identities", expanding=True))
    try:
        return list(db.scalars(statement, {
            "expression": expression,
            "identities": sorted(identity_ids),
            "limit": limit,
        }))
    except OperationalError:
        return []


def retrieve(
    query: str,
    memories: list[Memory],
    top_k: int = 5,
    min_similarity: float = 0.15,
) -> list[Memory]:
    """无数据库依赖的中文词法召回，供降级与深度召回使用。"""
    plan = build_query_plan(query)
    scored: list[tuple[float, Memory]] = []
    for memory in memories:
        similarity = max(
            (_lexical_similarity(variant, memory.content) for variant in plan.variants),
            default=0.0,
        )
        if similarity < min_similarity:
            continue
        scored.append((similarity * (1.0 + _importance(memory.importance)), memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:top_k]]


def hybrid_rank(
    db,
    query: str,
    memories: list[Memory],
    *,
    history: list[dict] | None = None,
    top_k: int = 6,
    lexical_limit: int = 30,
    vector_limit: int = 30,
) -> RecallTrace:
    plan = build_query_plan(query, history)
    if not memories or not plan.normalized:
        return RecallTrace(plan=plan, candidates=[], selected=[])

    return _rank_from_plan(
        db,
        plan,
        memories,
        embed_text(db, plan.normalized),
        top_k=top_k,
        lexical_limit=lexical_limit,
        vector_limit=vector_limit,
    )


async def hybrid_rank_async(
    db,
    query: str,
    memories: list[Memory],
    *,
    history: list[dict] | None = None,
    top_k: int = 6,
    lexical_limit: int = 30,
    vector_limit: int = 30,
    embedding_timeout: float = 1.5,
) -> RecallTrace:
    plan = build_query_plan(query, history)
    if not memories or not plan.normalized:
        return RecallTrace(plan=plan, candidates=[], selected=[])
    query_embedding = await embed_text_async(
        db, plan.normalized, timeout_seconds=embedding_timeout
    )
    return _rank_from_plan(
        db,
        plan,
        memories,
        query_embedding,
        top_k=top_k,
        lexical_limit=lexical_limit,
        vector_limit=vector_limit,
    )


def _rank_from_plan(
    db,
    plan: QueryPlan,
    memories: list[Memory],
    query_embedding: tuple[str, list[float]] | None,
    *,
    top_k: int,
    lexical_limit: int,
    vector_limit: int,
) -> RecallTrace:
    filtered: list[RankedMemory] = []
    core = [item for item in memories if item.tier == "core" and item.status == "active"]
    searchable: list[Memory] = []
    for memory in memories:
        reason = None
        if memory.status != "active":
            reason = f"lifecycle:{memory.status}"
        elif plan.temporal_intent == "current" and memory.tier == "episodic":
            if any(
                item.type == memory.type
                and (
                    (
                        item.supersession_key
                        and item.supersession_key == memory.supersession_key
                    )
                    or _lexical_similarity(item.content, memory.content) >= 0.25
                )
                for item in core
            ):
                reason = "current_core_overrides_history"
        if reason:
            filtered.append(
                RankedMemory(
                    memory=memory,
                    rrf_score=0.0,
                    confidence=0.0,
                    filtered_reason=reason,
                )
            )
        else:
            searchable.append(memory)

    channels: dict[str, list[tuple[float, Memory]]] = {
        "exact": [],
        "trigger": [],
        "lexical": [],
        "bm25": [],
        "vector": [],
    }
    by_id = {memory.id: memory for memory in searchable}
    fts_ids = fts_ranked_ids(
        db, plan.original,
        {memory.identity_id for memory in searchable if memory.identity_id},
        limit=lexical_limit,
    )
    for rank, memory_id in enumerate(fts_ids, 1):
        memory = by_id.get(memory_id)
        if memory is not None:
            channels["bm25"].append((1.0 / rank, memory))
    query_features = [
        (_ngrams(variant, 2), _ngrams(variant, 3))
        for variant in plan.variants
    ]
    for memory in searchable:
        content = normalize_text(memory.content)
        compact = "".join(content.split())
        exact = max(
            (
                1.0
                if variant and (variant in content or content in variant)
                else 0.0
                for variant in plan.variants
            ),
            default=0.0,
        )
        if exact:
            channels["exact"].append((exact, memory))

        triggers = [normalize_text(item) for item in (memory.trigger_text or "").split(",") if item.strip()]
        trigger_score = max(
            (
                1.0
                if trigger and any(trigger in variant or variant in trigger for variant in plan.variants)
                else 0.0
                for trigger in triggers
            ),
            default=0.0,
        )
        if trigger_score:
            channels["trigger"].append((trigger_score, memory))

        lexical = _lexical_similarity_features(
            query_features,
            (
                _ngrams_compact(compact, 2),
                _ngrams_compact(compact, 3),
            ),
        )
        if lexical >= 0.12:
            channels["lexical"].append((lexical, memory))

    if query_embedding is not None:
        model, query_vec = query_embedding
        vectors = load_vectors(db, [item.id for item in searchable], model=model)
        for memory in searchable:
            vector = vectors.get(memory.id)
            similarity = _cosine(query_vec, vector) if vector is not None else 0.0
            if similarity >= 0.35:
                channels["vector"].append((similarity, memory))

    limits = {"exact": 20, "trigger": 10, "lexical": lexical_limit, "bm25": lexical_limit, "vector": vector_limit}
    for name, values in channels.items():
        values.sort(key=lambda item: item[0], reverse=True)
        channels[name] = values[: limits[name]]

    fused: dict[str, RankedMemory] = {}
    for channel_name, values in channels.items():
        for rank, (raw_score, memory) in enumerate(values, 1):
            item = fused.setdefault(
                memory.id,
                RankedMemory(memory=memory, rrf_score=0.0, confidence=0.0),
            )
            item.rrf_score += 1.0 / (60 + rank)
            item.channels[channel_name] = raw_score
            item.confidence = max(item.confidence, raw_score)

    candidates = list(fused.values())
    for candidate in candidates:
        candidate.rrf_score *= _ranking_factor(candidate.memory, plan)
    candidates.sort(
        key=lambda item: (
            item.rrf_score,
            item.channels.get("lexical", 0.0),
            item.confidence,
        ),
        reverse=True,
    )

    eligible = [item for item in candidates if _passes_gate(item)]
    selected = _mmr(eligible, top_k)
    return RecallTrace(plan=plan, candidates=[*candidates, *filtered], selected=selected)


def hybrid_retrieve(
    db,
    query: str,
    memories: list[Memory],
    top_k: int = 5,
    *,
    history: list[dict] | None = None,
) -> list[Memory]:
    return [
        item.memory
        for item in hybrid_rank(db, query, memories, history=history, top_k=top_k).selected
    ]


def _passes_gate(item: RankedMemory) -> bool:
    if "exact" in item.channels or "trigger" in item.channels:
        return True
    if item.channels.get("vector", 0.0) >= 0.35:
        return True
    return item.channels.get("lexical", 0.0) >= 0.12


def _importance(value: float | None) -> float:
    number = float(value or 0.0)
    if number > 1.0:
        number /= 10.0
    return max(0.0, min(1.0, number))


def _ranking_factor(memory: Memory, plan: QueryPlan) -> float:
    factor = 1.0 + 0.2 * _importance(memory.importance)
    if memory.tier == "core":
        factor *= 1.05
    elif memory.observed_at:
        observed = memory.observed_at
        now = utcnow()
        age_days = max(0.0, (now - observed).total_seconds() / 86400)
        if plan.temporal_intent != "past":
            factor *= 0.5 ** (age_days / 30.0)
    return factor


def _mmr(candidates: list[RankedMemory], top_k: int, lambda_: float = 0.7) -> list[RankedMemory]:
    remaining = list(candidates)
    selected: list[RankedMemory] = []
    while remaining and len(selected) < top_k:
        best = max(
            remaining,
            key=lambda item: lambda_ * item.rrf_score
            - (1 - lambda_)
            * max(
                (
                    _lexical_similarity(item.memory.content, chosen.memory.content)
                    for chosen in selected
                ),
                default=0.0,
            ),
        )
        selected.append(best)
        remaining.remove(best)
    return selected
