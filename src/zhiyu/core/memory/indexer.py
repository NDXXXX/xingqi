"""索引重建：把文件内容同步回 SQLite 索引，并回填尚无文件的旧核心记忆。

文件是权威源；索引是可重建的缓存。重建规则：
- 旧核心记忆（``file_path`` 为空）先追加进对应文件并记录位置。
- 文件条目按 ``content_hash`` 匹配索引行；原地编辑（同位置、内容不同）就地更新；
  整行被删除则标记 ``invalidated``。
- 文件里新增的条目创建索引行。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from .store import CORE_FILE, USER_FILE, MemoryStore


def rebuild_index(db: Session, store: MemoryStore) -> dict[str, int]:
    repo = MemoryRepository()
    identity_id = IdentityRepository().local(db).id
    stats = {"backfilled": 0, "updated": 0, "created": 0, "invalidated": 0}

    # 1. 回填旧核心记忆：file_path 为空且有效的核心记录。
    legacy = db.scalars(
        select(Memory).where(
            Memory.identity_id == identity_id,
            Memory.tier == "core",
            Memory.status == "active",
            Memory.file_path.is_(None),
        )
    ).all()
    for memory in legacy:
        path = store.path_for(memory.type)
        entry = store.append(path, memory.content, meta={"type": memory.type})
        repo.update(
            db,
            memory,
            content=entry.content,
            file_path=path.name,
            line_start=entry.line_start,
            line_end=entry.line_end,
            content_hash=entry.hash,
        )
        stats["backfilled"] += 1

    # 2. 文件 → 索引。
    for path in store.list_memory_files():
        if not path.exists():
            continue
        entries = store.read_entries(path)
        by_hash = {entry.hash: entry for entry in entries}
        file_name = path.name
        tier = "core" if file_name in (USER_FILE, CORE_FILE) else "episodic"

        rows = db.scalars(
            select(Memory).where(Memory.identity_id == identity_id, Memory.file_path == file_name)
        ).all()
        consumed: set[str] = set()
        for row in rows:
            if row.content_hash in by_hash:
                entry = by_hash[row.content_hash]
                repo.update(
                    db,
                    row,
                    content=entry.content,
                    line_start=entry.line_start,
                    line_end=entry.line_end,
                )
                consumed.add(entry.hash)
                stats["updated"] += 1
                continue
            same_position = next(
                (entry for entry in entries if entry.line_start == row.line_start), None
            )
            if same_position is not None:
                repo.update(
                    db,
                    row,
                    content=same_position.content,
                    content_hash=same_position.hash,
                    line_start=same_position.line_start,
                    line_end=same_position.line_end,
                )
                consumed.add(same_position.hash)
                stats["updated"] += 1
            else:
                repo.update(db, row, status="invalidated", file_path=None, content_hash=None)
                stats["invalidated"] += 1

        for entry in entries:
            if entry.hash in consumed:
                continue
            repo.create(
                db,
                type=entry.meta.get("type", "fact"),
                content=entry.content,
                identity_id=identity_id,
                origin="manual",
                tier=tier,
                trust="owner" if tier == "core" else "agent",
                source_kind="manual",
                promotion_status="none" if tier == "core" else "pending",
                file_path=file_name,
                line_start=entry.line_start,
                line_end=entry.line_end,
                content_hash=entry.hash,
            )
            stats["created"] += 1

    db.commit()
    return stats
