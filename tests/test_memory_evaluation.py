"""固定检索评测必须覆盖足量 hard negatives、空结果和分层指标。"""

import runpy
from pathlib import Path


def test_production_retrieval_evaluation_meets_thresholds():
    evaluate = runpy.run_path(
        Path(__file__).resolve().parents[1] / "scripts" / "evaluate_memory_retrieval.py",
        run_name="memory_retrieval_evaluation",
    )["evaluate"]
    report = evaluate()
    overall = report["overall"]
    assert overall["cases"] >= 200
    assert report["candidate_pool_size"] >= 50
    assert overall["candidate_recall_at_30"] >= 0.99
    assert overall["recall_at_1"] >= 0.85
    assert overall["recall_at_3"] >= 0.94
    assert overall["recall_at_6"] >= 0.97
    assert overall["mrr"] >= 0.90
    assert overall["empty_accuracy"] >= 0.95
    assert report["groups"]["split:holdout"]["recall_at_3"] >= 0.94
    minimum_categories = {
        "synonym": 25,
        "reference": 20,
        "temporal": 20,
        "entity_alias": 15,
        "cross_session": 20,
        "empty": 20,
    }
    for category, minimum in minimum_categories.items():
        metrics = report["groups"][f"category:{category}"]
        assert metrics["cases"] >= minimum
        if category == "empty":
            assert metrics["empty_accuracy"] >= 0.95
        else:
            assert metrics["recall_at_3"] >= 0.90
