"""可恢复的记忆文件修改。

SQLite 和文件系统不能共享事务。先持久化 mutation，再幂等修改文件；调用者在
完成数据库索引/来源更新后把 mutation 标记为 completed。进程中断后可以安全
重放 prepared 操作，file_applied 操作则等待索引恢复。
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from zhiyu.infrastructure.database.models import Memory, MemoryMutation, utcnow
from .store import Entry, MemoryStore, content_hash, file_hash


class FileMutationManager:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def append(
        self,
        db: Session,
        identity_id: str,
        path,
        content: str,
        *,
        meta: dict[str, str] | None = None,
        context: dict | None = None,
    ) -> tuple[Entry, MemoryMutation]:
        metadata = dict(meta or {})
        entry_key = metadata.setdefault("id", str(uuid4()))
        mutation = self._prepare(
            db,
            identity_id,
            "append",
            path,
            entry_key,
            {"content": content, "meta": metadata, "context": context or {}},
        )
        entry = self._apply_append(db, mutation)
        return entry, mutation

    def remove(
        self,
        db: Session,
        identity_id: str,
        path,
        entry_key: str,
        *,
        context: dict | None = None,
    ) -> MemoryMutation:
        mutation = self._prepare(
            db,
            identity_id,
            "remove",
            path,
            entry_key,
            {"context": context or {}},
        )
        self._apply_remove(db, mutation)
        return mutation

    def replace(
        self,
        db: Session,
        identity_id: str,
        path,
        old_entry_key: str,
        content: str,
        *,
        meta: dict[str, str] | None = None,
        context: dict | None = None,
    ) -> tuple[Entry, MemoryMutation]:
        metadata = dict(meta or {})
        metadata.setdefault("id", str(uuid4()))
        mutation = self._prepare(
            db,
            identity_id,
            "replace",
            path,
            old_entry_key,
            {"content": content, "meta": metadata, "context": context or {}},
        )
        entry = self._apply_replace(db, mutation)
        return entry, mutation

    def complete(self, db: Session, mutation: MemoryMutation) -> None:
        mutation.status = "completed"
        mutation.updated_at = utcnow()
        db.flush()

    def recover_prepared(self, db: Session, identity_id: str | None = None) -> int:
        query = select(MemoryMutation).where(MemoryMutation.status == "prepared")
        if identity_id:
            query = query.where(MemoryMutation.identity_id == identity_id)
        recovered = 0
        for mutation in db.scalars(query.order_by(MemoryMutation.created_at)):
            try:
                if mutation.operation == "append":
                    self._apply_append(db, mutation)
                elif mutation.operation == "remove":
                    self._apply_remove(db, mutation)
                elif mutation.operation == "replace":
                    self._apply_replace(db, mutation)
                else:
                    self._fail(db, mutation, "未知 mutation 操作")
                    continue
                recovered += 1
            except Exception as exc:
                self._fail(db, mutation, str(exc))
        return recovered

    def reconcile_file_applied(
        self, db: Session, identity_id: str | None = None
    ) -> int:
        """索引重建后，把文件与 SQLite 已收敛的操作标记为完成。"""
        query = select(MemoryMutation).where(
            MemoryMutation.status == "file_applied"
        )
        if identity_id:
            query = query.where(MemoryMutation.identity_id == identity_id)
        completed = 0
        for mutation in db.scalars(query.order_by(MemoryMutation.created_at)):
            key = mutation.entry_key
            if mutation.operation == "replace":
                payload = json.loads(mutation.new_entry_text or "{}")
                key = payload.get("meta", {}).get("id", "")
            row = db.scalars(
                select(Memory).where(
                    Memory.identity_id == mutation.identity_id,
                    Memory.entry_key == key,
                )
            ).first()
            converged = (
                row is None or row.status != "active"
                if mutation.operation == "remove"
                else row is not None and row.status == "active"
            )
            if converged:
                self.complete(db, mutation)
                completed += 1
        return completed

    def _prepare(
        self,
        db: Session,
        identity_id: str,
        operation: str,
        path,
        entry_key: str,
        payload: dict | None,
    ) -> MemoryMutation:
        self._validate_path(identity_id, path)
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        mutation = MemoryMutation(
            id=str(uuid4()),
            identity_id=identity_id,
            operation=operation,
            relative_path=self.store.relative_path(path),
            entry_key=entry_key,
            expected_file_hash=file_hash(current),
            new_entry_text=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            new_entry_hash=(
                content_hash(str(payload["content"]))
                if payload is not None and "content" in payload
                else None
            ),
            status="prepared",
            attempts=0,
        )
        db.add(mutation)
        db.commit()
        db.refresh(mutation)
        return mutation

    def _apply_append(self, db: Session, mutation: MemoryMutation) -> Entry:
        path = self.store.resolve_relative(mutation.relative_path)
        self._validate_path(mutation.identity_id, path)
        existing_index = self.store.index_by_id(path, mutation.entry_key)
        if existing_index is not None:
            entry = self.store.read_entries(path)[existing_index]
            if entry.hash != mutation.new_entry_hash:
                raise RuntimeError("entry id 已存在但内容不一致")
            self._mark_applied(db, mutation)
            return entry
        payload = json.loads(mutation.new_entry_text or "{}")
        entry = self.store.append(
            path,
            payload["content"],
            meta=payload["meta"],
            expected_file_hash=mutation.expected_file_hash,
        )
        self._mark_applied(db, mutation)
        return entry

    def _apply_remove(self, db: Session, mutation: MemoryMutation) -> None:
        path = self.store.resolve_relative(mutation.relative_path)
        self._validate_path(mutation.identity_id, path)
        if self.store.index_by_id(path, mutation.entry_key) is None:
            self._mark_applied(db, mutation)
            return
        self.store.remove_by_id(
            path,
            mutation.entry_key,
            expected_file_hash=mutation.expected_file_hash,
        )
        self._mark_applied(db, mutation)

    def _apply_replace(self, db: Session, mutation: MemoryMutation) -> Entry:
        path = self.store.resolve_relative(mutation.relative_path)
        self._validate_path(mutation.identity_id, path)
        payload = json.loads(mutation.new_entry_text or "{}")
        new_id = payload["meta"]["id"]
        new_index = self.store.index_by_id(path, new_id)
        if new_index is not None:
            entry = self.store.read_entries(path)[new_index]
            if entry.hash != mutation.new_entry_hash:
                raise RuntimeError("replacement entry id 已存在但内容不一致")
            self._mark_applied(db, mutation)
            return entry
        entry = self.store.replace_by_id(
            path,
            mutation.entry_key,
            payload["content"],
            payload["meta"],
            expected_file_hash=mutation.expected_file_hash,
        )
        self._mark_applied(db, mutation)
        return entry

    @staticmethod
    def _mark_applied(db: Session, mutation: MemoryMutation) -> None:
        mutation.status = "file_applied"
        mutation.attempts += 1
        mutation.last_error = None
        mutation.updated_at = utcnow()
        db.commit()
        db.refresh(mutation)

    @staticmethod
    def _fail(db: Session, mutation: MemoryMutation, error: str) -> None:
        mutation.status = "failed"
        mutation.attempts += 1
        mutation.last_error = error[:2000]
        mutation.updated_at = utcnow()
        db.commit()

    def _validate_path(self, identity_id: str, path) -> None:
        resolved = path.resolve()
        vault = self.store.vault_dir(identity_id).resolve()
        if not resolved.is_relative_to(vault):
            raise ValueError("mutation 目标不属于当前身份 vault")
