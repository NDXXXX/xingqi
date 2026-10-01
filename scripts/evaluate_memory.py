"""Run the fixed memory-extraction evaluation set against a configured provider."""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from zhiyu.core.memory.extractor import extract_operations
from zhiyu.core.providers.router import provider_router
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "memory_extraction_cases.json"


def _signature(operation: dict) -> tuple[str, str, str]:
    return (
        operation.get("action", ""),
        operation.get("type", ""),
        operation.get("target_id", ""),
    )


async def evaluate(
    provider_name: str,
    model_name: str | None,
    limit: int | None,
    case_ids: set[str],
) -> int:
    with SessionLocal() as db:
        config = ProviderRepository().get_by_name(db, provider_name)
        if config is None or not config.enabled:
            raise ValueError("Provider 不存在或未启用")
        models = [item.model_name for item in config.models if item.enabled]
        model = model_name or (models[0] if models else None)
        if model not in models:
            raise ValueError("模型不存在或未启用")
        client = provider_router.get_provider(config)
    if not client.api_key:
        raise ValueError("Provider 凭据不可用")

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if case_ids:
        cases = [case for case in cases if case["id"] in case_ids]
    if limit is not None:
        cases = cases[:limit]
    passed = 0
    false_writes = 0
    details = []
    for case in cases:
        raw_actual = await extract_operations(
            client,
            model,
            user_message=case["user"],
            assistant_message=case["assistant"],
            history=case.get("history", []),
            memories=case.get("memories", []),
        )
        actual = [
            operation
            for operation in raw_actual
            if not (
                operation.get("action") == "add"
                and any(
                    old.get("type") == operation.get("type")
                    and old.get("content", "").strip() == operation.get("content", "").strip()
                    for old in case.get("memories", [])
                )
            )
        ]
        expected_signatures = sorted(_signature(item) for item in case["expected"])
        actual_signatures = sorted(_signature(item) for item in actual)
        forbidden = case.get("forbidden_terms", [])
        forbidden_found = [
            term
            for term in forbidden
            if any(term in operation.get("content", "") for operation in actual)
        ]
        if case.get("allow_multiple"):
            signatures_match = bool(actual_signatures) and set(actual_signatures) == set(
                expected_signatures
            )
        else:
            signatures_match = actual_signatures == expected_signatures
        if case.get("optional_write") and not actual_signatures:
            signatures_match = True
        ok = signatures_match and not forbidden_found
        passed += int(ok)
        if not case["expected"] and actual:
            false_writes += 1
        details.append(
            {
                "id": case["id"],
                "passed": ok,
                "expected": expected_signatures,
                "actual": actual_signatures,
                "actual_operations": actual,
                "raw_operations": raw_actual,
                "forbidden_found": forbidden_found,
            }
        )
        print(f"{'PASS' if ok else 'FAIL'} {case['id']}")

    report = {
        "provider": provider_name,
        "model": model,
        "passed": passed,
        "total": len(cases),
        "accuracy": round(passed / len(cases), 4) if cases else 0,
        "false_write_cases": false_writes,
        "details": details,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed == len(cases) else 1


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    try:
        raise SystemExit(
            asyncio.run(evaluate(args.provider, args.model, args.limit, set(args.cases or [])))
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
