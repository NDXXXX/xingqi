"""Evaluate the production memory ranker with hard negatives and empty queries."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from zhiyu.core.memory.retriever import derive_trigger_text, hybrid_rank
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import Memory


CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "memory_retrieval_cases.json"


def _memory(id: str, content: str) -> Memory:
    return Memory(
        id=id,
        identity_id="evaluation",
        type="fact",
        content=content,
        importance=0.5,
        status="active",
        tier="core",
        trigger_text=derive_trigger_text(content),
    )


def _positive_cases(data: dict) -> list[dict]:
    cases: list[dict] = []
    index = 0
    for target in data["targets"]:
        for query in target["queries"]:
            cases.append(
                {
                    "id": f"{target['id']}-{index % 4 + 1}",
                    "query": query,
                    "target": target["target"],
                    "history": [],
                    "category": "direct" if index % 4 < 2 else "rewrite",
                    "split": "dev" if index % 2 == 0 else "holdout",
                }
            )
            index += 1
    for offset, case in enumerate(data["stress_cases"]):
        cases.append(
            {
                **case,
                "history": [],
                "split": "dev" if offset % 2 == 0 else "holdout",
            }
        )
    for offset, case in enumerate(data["context_cases"]):
        cases.append(
            {
                **case,
                "history": [{"role": "user", "content": case["history"]}],
                "category": "reference",
                "split": "dev" if offset % 2 == 0 else "holdout",
            }
        )
    for offset, case in enumerate(data.get("category_cases", [])):
        history = case.get("history")
        cases.append(
            {
                **case,
                "history": (
                    [{"role": "user", "content": history}] if history else []
                ),
                "split": case.get(
                    "split", "dev" if offset % 2 == 0 else "holdout"
                ),
            }
        )
    return cases


def _summarize(rows: list[dict]) -> dict[str, float | int]:
    positives = [row for row in rows if not row["empty"]]
    empty = [row for row in rows if row["empty"]]
    return {
        "cases": len(rows),
        "candidate_recall_at_30": round(
            sum(row["candidate_hit"] for row in positives) / len(positives), 4
        )
        if positives
        else 0,
        "recall_at_1": round(sum(row["rank"] == 1 for row in positives) / len(positives), 4)
        if positives
        else 0,
        "recall_at_3": round(
            sum(0 < row["rank"] <= 3 for row in positives) / len(positives), 4
        )
        if positives
        else 0,
        "recall_at_6": round(
            sum(0 < row["rank"] <= 6 for row in positives) / len(positives), 4
        )
        if positives
        else 0,
        "mrr": round(
            sum(1 / row["rank"] if row["rank"] else 0 for row in positives)
            / len(positives),
            4,
        )
        if positives
        else 0,
        "ndcg_at_6": round(
            sum(
                1 / math.log2(row["rank"] + 1)
                if 0 < row["rank"] <= 6
                else 0
                for row in positives
            )
            / len(positives),
            4,
        )
        if positives
        else 0,
        "empty_accuracy": round(sum(row["rank"] == 0 for row in empty) / len(empty), 4)
        if empty
        else 0,
    }


def evaluate() -> dict:
    data = json.loads(CASES.read_text(encoding="utf-8"))
    positive = _positive_cases(data)
    targets: dict[str, Memory] = {}
    for case in positive:
        if case["target"] not in targets:
            targets[case["target"]] = _memory(
                f"target-{len(targets)}", case["target"]
            )
    hard_negatives = [
        _memory(f"negative-{index}", content)
        for index, content in enumerate(data["hard_negatives"])
    ]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    rows: list[dict] = []
    with Session(engine) as db:
        for index, case in enumerate(positive):
            target = targets[case["target"]]
            trace = hybrid_rank(
                db,
                case["query"],
                [*targets.values(), *hard_negatives],
                history=case["history"],
                top_k=6,
            )
            selected = [item.memory.id for item in trace.selected]
            rank = selected.index(target.id) + 1 if target.id in selected else 0
            rows.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "split": case["split"],
                    "empty": False,
                    "rank": rank,
                    "candidate_hit": any(
                        item.memory.id == target.id for item in trace.candidates
                    ),
                }
            )
        for index, query in enumerate(data["empty_queries"]):
            trace = hybrid_rank(db, query, hard_negatives, top_k=6)
            rows.append(
                {
                    "id": f"empty-{index + 1}",
                    "category": "empty",
                    "split": "dev" if index % 2 == 0 else "holdout",
                    "empty": True,
                    "rank": len(trace.selected),
                    "candidate_hit": False,
                }
            )

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[f"split:{row['split']}"].append(row)
        groups[f"category:{row['category']}"].append(row)
    report = {
        "mode": "production_hybrid_rank_lexical_fallback",
        "candidate_pool_size": len(hard_negatives) + len(targets),
        "overall": _summarize(rows),
        "groups": {name: _summarize(items) for name, items in sorted(groups.items())},
        "non_top1": [
            row
            for row in rows
            if (row["empty"] and row["rank"])
            or (not row["empty"] and row["rank"] != 1)
        ],
    }
    return report


def main() -> None:
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    overall = report["overall"]
    failed = (
        overall["candidate_recall_at_30"] < 0.99
        or overall["recall_at_1"] < 0.85
        or overall["recall_at_3"] < 0.94
        or overall["recall_at_6"] < 0.97
        or overall["mrr"] < 0.90
        or overall["empty_accuracy"] < 0.95
    )
    for name, metrics in report["groups"].items():
        if name.startswith("category:empty"):
            failed = failed or metrics["empty_accuracy"] < 0.95
        elif name.startswith("category:"):
            failed = failed or metrics["recall_at_3"] < 0.90
        elif name.startswith("split:"):
            failed = failed or metrics["recall_at_3"] < 0.94
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
