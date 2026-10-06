"""长期核心巩固：让模型从情景观察中挑选稳定信息，晋升为长期核心记忆。

第一版是单次 sweep（合并 OpenClaw 的 light/REM/deep）：
- 代码负责候选边界、信任门槛、结构校验、文件写入与生命周期；
- 模型只负责在受约束的候选内产出 add_core / supersede_core / ignore。
- 调度层在模型调用前校验召回次数、独立复现、owner 确认与正文版本。
"""

from __future__ import annotations

import json
import re
from uuid import uuid4
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory, MemorySource
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.core.providers.base import AIProvider
from zhiyu.core.providers.embedding import embed_and_store
from .extractor import MEMORY_TYPES
from .mutations import FileMutationManager
from .retriever import derive_trigger_text
from .store import MemoryStore

CONSOLIDATION_ACTIONS = ("add_core", "supersede_core", "ignore")

_PROMPT = """你是记忆巩固器。从情景观察里挑出真正稳定、反复出现、会长期影响回答的信息，晋升为长期核心；其余忽略。

规则：
- 只有被多次观察、或明显代表用户稳定状态/偏好的信息才晋升；一次性、试探性、不确定的表达一律 ignore。
- add_core：把一个或多个表达同一事实的候选合并成一条新的核心记忆。
- supersede_core：当候选更新或推翻了某条已有核心记忆时，替换它（target_id 指向旧核心）。
- ignore：本轮证据不足时暂缓，未来有新的独立相关观察后可以重新评估；给出简短原因。
- 只能引用下面给出的候选 id 与核心 id，不能编造。每个候选最多出现在一项操作里。
- importance 取 1–10（10 最重要）。
- 只返回 JSON 数组，格式：
  {{"action":"add_core","candidate_ids":["..."],"type":"...","content":"...","importance":8}}
  {{"action":"supersede_core","target_id":"...","candidate_ids":["..."],"type":"...","content":"...","importance":8}}
  {{"action":"ignore","candidate_ids":["..."],"reason":"证据不足"}}

候选情景观察：
{candidates}

当前长期核心：
{core}"""


def _load_array(text: str) -> list | None:
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", text.strip(), flags=re.DOTALL)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, list) else None


def build_prompt(candidates: list[Memory], core: list[Memory]) -> str:
    serialized_candidates = [
        {"id": item.id, "type": item.type, "content": item.content}
        for item in candidates
    ]
    serialized_core = [
        {"id": item.id, "type": item.type, "content": item.content} for item in core
    ]
    return _PROMPT.format(
        candidates=json.dumps(serialized_candidates, ensure_ascii=False),
        core=json.dumps(serialized_core, ensure_ascii=False),
    )


def parse_consolidation(text: str) -> list[dict]:
    """严格解析巩固协议；任意结构错误拒绝整批。"""
    data = _load_array(text)
    if data is None or len(data) > 20:
        return []
    operations: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            return []
        action = str(item.get("action", "")).strip().lower()
        if action not in CONSOLIDATION_ACTIONS:
            return []
        operation = {"action": action}
        reason = str(item.get("reason", "")).strip()
        if reason:
            operation["reason"] = reason[:300]
        candidate_ids = item.get("candidate_ids", [])
        if not isinstance(candidate_ids, list) or not candidate_ids:
            return []
        operation["candidate_ids"] = [str(cid) for cid in candidate_ids]
        if action == "ignore":
            operations.append(operation)
            continue
        memory_type = str(item.get("type", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if memory_type not in MEMORY_TYPES or not content or len(content) > 500:
            return []
        operation["type"] = memory_type
        operation["content"] = content
        try:
            importance = float(item.get("importance", 5))
        except (TypeError, ValueError):
            importance = 5
        operation["importance"] = max(0.0, min(10.0, importance))
        if action == "supersede_core":
            target_id = str(item.get("target_id", "")).strip()
            if not target_id:
                return []
            operation["target_id"] = target_id
        operations.append(operation)
    return operations


async def propose(
    provider: AIProvider, model: str, candidates: list[Memory], core: list[Memory]
) -> list[dict]:
    response = await provider.chat(
        messages=[{"role": "user", "content": build_prompt(candidates, core)}],
        model=model,
        stream=False,
        temperature=0,
    )
    return parse_consolidation(response.content or "")


def apply_consolidation(
    db: Session,
    store: MemoryStore,
    identity_id: str,
    operations: list[dict],
    *,
    dry_run: bool = False,
) -> dict:
    """校验并应用巩固操作；任何结构/边界违规整批拒绝。"""
    repo = MemoryRepository()
    mutations = FileMutationManager(store)
    applied_mutations = []
    stats = {
        "candidate_count": 0,
        "promoted_count": 0,
        "superseded_count": 0,
        "skipped_count": 0,
        "merged_count": 0,
        "deferred_count": 0,
        "core_ids": [],
        "decisions": [],
    }

    candidates = _load_candidates(db, repo, identity_id, operations)
    targets = _load_targets(db, repo, identity_id, operations)
    if candidates is None or targets is None:
        return stats

    for operation in operations:
        for candidate_id in operation["candidate_ids"]:
            stats["candidate_count"] += 1
            if operation["action"] == "ignore":
                stats["skipped_count"] += 1

    if dry_run:
        for operation in operations:
            if operation["action"] in ("add_core", "supersede_core"):
                stats["promoted_count"] += 1
                if operation["action"] == "supersede_core":
                    stats["superseded_count"] += 1
        return stats

    for operation in operations:
        if operation["action"] == "ignore":
            for candidate_id in operation["candidate_ids"]:
                repo.update(db, candidates[candidate_id], promotion_status="deferred")
                stats["decisions"].append(
                    {
                        "candidate_id": candidate_id,
                        "decision": "deferred",
                        "reason": operation.get("reason", "本轮证据不足"),
                    }
                )
                stats["deferred_count"] += 1
            continue

        if operation["action"] == "supersede_core":
            target = targets[operation["target_id"]]
            if target.file_path and target.entry_key:
                mutation = mutations.remove(
                    db,
                    identity_id,
                    store.resolve_relative(target.file_path),
                    target.entry_key,
                    context={"lifecycle": "superseded"},
                )
                applied_mutations.append(mutation)
            elif target.content_hash:
                target_path = (
                    store.resolve_relative(target.file_path)
                    if target.file_path
                    else store.path_for(target.type, identity_id)
                )
                store.remove_by_hash(
                    target_path, target.content_hash
                )
            repo.update(
                db,
                target,
                status="superseded",
                file_path=None,
                line_start=None,
                line_end=None,
                content_hash=None,
            )
            stats["superseded_count"] += 1

        core, mutation = _create_core(
            db, repo, store, mutations, identity_id, operation, candidates
        )
        applied_mutations.append(mutation)
        stats["core_ids"].append(core.id)
        stats["promoted_count"] += 1
        stats["decisions"].append(
            {
                "candidate_ids": list(operation["candidate_ids"]),
                "decision": operation["action"],
                "content": operation["content"],
                "target_id": operation.get("target_id"),
                "reason": operation.get("reason", "达到沉淀条件"),
            }
        )

    for mutation in applied_mutations:
        mutations.complete(db, mutation)
    _append_dreams(store, identity_id, stats)
    db.commit()
    return stats


def _load_candidates(db, repo, identity_id, operations) -> dict[str, Memory] | None:
    referenced: set[str] = set()
    for operation in operations:
        for candidate_id in operation["candidate_ids"]:
            if candidate_id in referenced:
                return None
            referenced.add(candidate_id)
    result: dict[str, Memory] = {}
    for candidate_id in referenced:
        memory = repo.get_owned(db, identity_id, candidate_id)
        if (
            memory is None
            or memory.tier != "episodic"
            or memory.status != "active"
            or memory.promotion_status != "pending"
        ):
            return None
        result[candidate_id] = memory
    return result


def _load_targets(db, repo, identity_id, operations) -> dict[str, Memory] | None:
    result: dict[str, Memory] = {}
    for operation in operations:
        if operation["action"] != "supersede_core":
            continue
        target_id = operation["target_id"]
        memory = repo.get_owned(db, identity_id, target_id)
        if (
            memory is None
            or memory.tier != "core"
            or memory.status != "active"
            or memory.type != operation["type"]
        ):
            return None
        result[target_id] = memory
    return result


def _create_core(db, repo, store, mutations, identity_id, operation, candidates):
    path = store.path_for(operation["type"], identity_id)
    meta = {"type": operation["type"], "importance": str(int(round(operation["importance"])))}
    entry, mutation = mutations.append(
        db,
        identity_id,
        path,
        operation["content"],
        meta=meta,
        context={
            "origin": "automatic",
            "tier": "core",
            "trust": "agent",
            "source_kind": "consolidation",
            "promotion_status": "none",
            "importance": operation["importance"],
            "source_memory_ids": list(operation["candidate_ids"]),
            "supersedes_id": operation.get("target_id"),
        },
    )
    core = repo.create(
        db,
        type=operation["type"],
        content=entry.content,
        identity_id=identity_id,
        importance=operation["importance"],
        origin="automatic",
        tier="core",
        trust="agent",
        source_kind="consolidation",
        trigger_text=derive_trigger_text(entry.content),
        file_path=store.relative_path(path),
        line_start=entry.line_start,
        line_end=entry.line_end,
        content_hash=entry.hash,
        entry_key=entry.id,
    )
    if operation["type"] in {"goal", "project"}:
        evidence_times = [
            candidates[candidate_id].observed_at
            for candidate_id in operation["candidate_ids"]
            if candidates[candidate_id].observed_at is not None
        ]
        if evidence_times:
            core.last_evidence_at = max(evidence_times)
    embed_and_store(db, core.id, core.content)
    for candidate_id in operation["candidate_ids"]:
        candidate = candidates[candidate_id]
        repo.update(
            db,
            candidate,
            promotion_status="promoted",
            promoted_to_id=core.id,
        )
        db.add(
            MemorySource(
                id=str(uuid4()),
                memory_id=core.id,
                identity_id=identity_id,
                source_memory_id=candidate.id,
                source_message_id=candidate.source_message_id,
                conversation_id=candidate.conversation_id,
                trust=candidate.trust,
                source_kind="consolidation",
                observed_at=candidate.observed_at,
            )
        )
    return core, mutation


def _append_dreams(store, identity_id, stats) -> None:
    summary = (
        f"候选 {stats['candidate_count']}：晋升 {stats['promoted_count']}，"
        f"替换 {stats['superseded_count']}，忽略 {stats['skipped_count']}"
    )
    store.append(store.dreams_path(identity_id), summary, meta={"identity": identity_id})
