"""Run the fixed observation-extraction evaluation set against a configured provider."""

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from zhiyu.core.memory.extractor import extract_observations
from zhiyu.core.providers.router import provider_router
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository


CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "memory_observation_cases.json"


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
        actual = await extract_observations(
            client,
            model,
            user_message=case["user"],
            assistant_message=case["assistant"],
            history=case.get("history", []),
        )
        expected_types = sorted(item["type"] for item in case["expected"])
        actual_types = sorted(observation["type"] for observation in actual)
        forbidden_found = [
            term
            for term in case.get("forbidden_terms", [])
            if any(term in observation["content"] for observation in actual)
        ]
        types_match = actual_types == expected_types
        if case.get("optional_write") and not actual:
            types_match = True
        ok = types_match and not forbidden_found
        passed += int(ok)
        if not case["expected"] and actual:
            false_writes += 1
        details.append(
            {
                "id": case["id"],
                "passed": ok,
                "expected_types": expected_types,
                "actual": actual,
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
