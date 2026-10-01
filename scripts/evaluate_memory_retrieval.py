"""Compare the current memory retriever with the original overlap scorer."""

import json
from pathlib import Path

from zhiyu.core.memory.retriever import _bigrams, retrieve
from zhiyu.infrastructure.database.models import Memory


CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "memory_retrieval_cases.json"
DISTRACTORS = [
    "用户喜欢喝咖啡",
    "用户正在学习摄影",
    "用户住在上海",
    "用户准备阅读历史书籍",
    "用户每周参加一次会议",
    "用户喜欢简洁回答",
    "用户养了一只狗",
]


def _memory(id: str, content: str) -> Memory:
    return Memory(id=id, type="fact", content=content, importance=0.5, status="active")


def _old_retrieve(query: str, memories: list[Memory], top_k: int = 5) -> list[Memory]:
    query_bigrams = _bigrams(query)
    scored = []
    for memory in memories:
        overlap = len(query_bigrams & _bigrams(memory.content))
        if overlap:
            scored.append((overlap * (1 + memory.importance), memory))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [memory for _, memory in scored[:top_k]]


def _metrics(cases: list[dict], use_current: bool) -> dict[str, float | int]:
    hits = 0
    returned = 0
    irrelevant = 0
    synonym_misses = 0
    for case in cases:
        memories = [_memory("target", case["target"])] + [
            _memory(f"distractor-{index}", content)
            for index, content in enumerate(DISTRACTORS)
            if content != case["target"]
        ]
        result = retrieve(case["query"], memories) if use_current else _old_retrieve(
            case["query"], memories
        )
        ids = {memory.id for memory in result}
        hit = "target" in ids
        hits += int(hit)
        returned += len(result)
        irrelevant += sum(memory.id != "target" for memory in result)
        if case["synonym"] and not hit:
            synonym_misses += 1
    return {
        "recall_at_5": round(hits / len(cases), 4),
        "irrelevant_ratio": round(irrelevant / returned, 4) if returned else 0,
        "synonym_misses": synonym_misses,
    }


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    old = _metrics(cases, False)
    current = _metrics(cases, True)
    report = {"cases": len(cases), "original": old, "current": current}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if current["recall_at_5"] < old["recall_at_5"]:
        raise SystemExit(1)
    if current["irrelevant_ratio"] > old["irrelevant_ratio"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
