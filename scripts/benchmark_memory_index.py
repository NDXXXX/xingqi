"""Run a synthetic memory-index and retrieval benchmark in an isolated database."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.core.memory.indexer import rebuild_index, sync_changed_index
from zhiyu.core.memory.retriever import hybrid_rank
from zhiyu.core.memory.store import MemoryStore
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository


def _percentiles(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "p50_ms": round(statistics.median(ordered) * 1000, 2),
        "p95_ms": round(ordered[p95_index] * 1000, 2),
    }


def benchmark(count: int, rounds: int) -> dict:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with tempfile.TemporaryDirectory(prefix="zhiyu-memory-benchmark-") as temp_dir:
        store = MemoryStore(Path(temp_dir) / "memory")
        with factory() as db:
            identity_id = IdentityRepository().local(db).id
        path = store.core_path_for(identity_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# 基准数据\n"
            + "".join(
                f"- 基准记忆 {index:05d}：用户偏好与项目事实样例。 <!-- id={uuid4()} -->\n"
                for index in range(count)
            ),
            encoding="utf-8",
        )

        started = time.perf_counter()
        with factory() as db:
            rebuild_index(db, store, identity_id)
        rebuild_seconds = time.perf_counter() - started

        sync_times = []
        sync_stats = None
        for _ in range(rounds):
            started = time.perf_counter()
            with factory() as db:
                sync_stats = sync_changed_index(db, store, identity_id)
            sync_times.append(time.perf_counter() - started)

        repository = MemoryRepository()
        retrieval_times = []
        candidate_count = 0
        for _ in range(rounds):
            started = time.perf_counter()
            with factory() as db:
                memories = repository.list_owned(db, identity_id)
                candidate_count = len(memories)
                hybrid_rank(db, "用户偏好与项目事实", memories, top_k=6)
            retrieval_times.append(time.perf_counter() - started)

    engine.dispose()
    return {
        "memory_count": count,
        "rounds": rounds,
        "rebuild_ms": round(rebuild_seconds * 1000, 2),
        "unchanged_sync": _percentiles(sync_times),
        "retrieval": _percentiles(retrieval_times),
        "candidate_count": candidate_count,
        "unchanged_sync_files_scanned": sync_stats["files_scanned"] if sync_stats else None,
        "unchanged_sync_files_changed": sync_stats["files_changed"] if sync_stats else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = {
        "format": 1,
        "python": __import__("platform").python_version(),
        "sqlite": __import__("sqlite3").sqlite_version,
        "results": [benchmark(count, args.rounds) for count in args.counts],
    }
    rendered = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
