"""文件权威的记忆存储：按身份隔离 Markdown，使用稳定 entry id 寻址。

文件布局（``settings.memory_dir`` 下）：
- ``identities/<identity_id>/USER.md`` 用户模型（profile / preference）
- ``identities/<identity_id>/IDENTITY.md`` 助手身份
- ``identities/<identity_id>/MEMORY.md`` 长期核心
- ``identities/<identity_id>/daily/YYYY-MM-DD.md`` 情景观察
- ``identities/<identity_id>/DREAMS.md`` 巩固审查日志

每行一条记忆，元数据用行尾 HTML 注释承载。``id`` 只负责稳定寻址，
身份、可信等级和来源仍由数据库确定，不能从 Markdown 注释提升权限。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from filelock import FileLock

from zhiyu.infrastructure.config.settings import settings

USER_FILE = "USER.md"
IDENTITY_FILE = "IDENTITY.md"
CORE_FILE = "MEMORY.md"
DREAMS_FILE = "DREAMS.md"

# 进入用户模型文件的类型；其余核心类型进入 MEMORY.md。
_USER_TYPES = ("profile", "preference")

_META_RE = re.compile(r"\s*<!--\s*(.*?)\s*-->\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.+)$")
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_LOCK_TIMEOUT_SECONDS = 5.0


def normalize(content: str) -> str:
    """折叠所有空白（含换行）为单个空格，保证行格式与哈希稳定。"""
    return " ".join(content.split())


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize(content).encode("utf-8")).hexdigest()


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Entry:
    content: str
    meta: dict[str, str] = field(default_factory=dict)
    line_start: int = 1
    line_end: int = 1

    @property
    def hash(self) -> str:
        return content_hash(self.content)

    @property
    def id(self) -> str | None:
        return self.meta.get("id")


def _parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for part in text.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        meta[key.strip()] = value.strip()
    return meta


def _format_line(content: str, meta: dict[str, str]) -> str:
    body = normalize(content)
    parts = [f"{k}={v}" for k, v in meta.items() if v is not None and v != ""]
    if not parts:
        return f"- {body}"
    return f"- {body} <!-- {', '.join(parts)} -->"


def parse_line(line: str, line_no: int) -> Entry | None:
    """把 Markdown bullet 解析为 Entry；标题和普通段落不会成为记忆。"""
    bullet = _BULLET_RE.match(line)
    if bullet is None:
        return None
    body = bullet.group(1)
    match = _META_RE.search(body)
    if match:
        content = normalize(body[: match.start()])
        meta = _parse_meta(match.group(1))
    else:
        content = normalize(body)
        meta = {}
    if not content:
        return None
    return Entry(content=content, meta=meta, line_start=line_no, line_end=line_no)


class MemoryStore:
    """记忆文件的读写；线程/进程间用 filelock 串行化写。"""

    def __init__(self, memory_dir: Path | None = None) -> None:
        self.dir = memory_dir or settings.memory_dir

    def _lock_for(self, path: Path) -> FileLock:
        return FileLock(
            str(path.parent / f".{path.name}.lock"),
            timeout=_LOCK_TIMEOUT_SECONDS,
        )

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def user_path(self) -> Path:
        """兼容无身份的离线测试/导入；产品写入必须传 identity_id。"""
        return self.dir / USER_FILE

    @property
    def core_path(self) -> Path:
        return self.dir / CORE_FILE

    def vault_dir(self, identity_id: str) -> Path:
        if not identity_id or not _IDENTITY_RE.fullmatch(identity_id):
            raise ValueError("无效的记忆身份")
        identities = (self.dir / "identities").resolve()
        vault = (identities / identity_id).resolve()
        if vault.parent != identities:
            raise ValueError("无效的记忆身份")
        return vault

    def user_path_for(self, identity_id: str) -> Path:
        return self.vault_dir(identity_id) / USER_FILE

    def identity_path_for(self, identity_id: str) -> Path:
        return self.vault_dir(identity_id) / IDENTITY_FILE

    def assistant_name(self, identity_id: str) -> str | None:
        for entry in reversed(self.read_entries(self.identity_path_for(identity_id))):
            if entry.content.startswith("助手名字是 "):
                return entry.content.removeprefix("助手名字是 ").strip() or None
        return None

    def core_path_for(self, identity_id: str) -> Path:
        return self.vault_dir(identity_id) / CORE_FILE

    def dreams_path(self, identity_id: str) -> Path:
        return self.vault_dir(identity_id) / DREAMS_FILE

    def daily_path(self, when: datetime | None = None, identity_id: str | None = None) -> Path:
        if when is None:
            current = datetime.now(_LOCAL_TZ)
        elif when.tzinfo is None:
            current = when.replace(tzinfo=timezone.utc).astimezone(_LOCAL_TZ)
        else:
            current = when.astimezone(_LOCAL_TZ)
        root = self.vault_dir(identity_id) / "daily" if identity_id else self.dir
        return root / f"{current.strftime('%Y-%m-%d')}.md"

    def path_for(self, memory_type: str, identity_id: str | None = None) -> Path:
        if identity_id:
            return (
                self.user_path_for(identity_id)
                if memory_type in _USER_TYPES
                else self.core_path_for(identity_id)
            )
        return self.user_path if memory_type in _USER_TYPES else self.core_path

    def relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        root = self.dir.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("记忆文件必须位于 memory_dir 内")
        return resolved.relative_to(root).as_posix()

    def resolve_relative(self, relative_path: str) -> Path:
        path = (self.dir / relative_path).resolve()
        if not path.is_relative_to(self.dir.resolve()):
            raise ValueError("记忆文件路径越界")
        return path

    def list_memory_files(self, identity_id: str | None = None) -> list[Path]:
        """只返回受管的 USER、MEMORY 和 daily 文件。"""
        if identity_id:
            vault = self.vault_dir(identity_id)
            files = [
                self.identity_path_for(identity_id),
                self.user_path_for(identity_id),
                self.core_path_for(identity_id),
            ]
            daily = vault / "daily"
            if daily.exists():
                files.extend(sorted(daily.glob("????-??-??.md")))
            return files
        files = [self.user_path, self.core_path]
        if self.dir.exists():
            files.extend(sorted(self.dir.glob("????-??-??.md")))
        return files

    def is_managed_path(self, identity_id: str, path: Path) -> bool:
        """路径是否是该身份可被索引的正文文件（明确排除 DREAMS）。"""
        resolved = path.resolve()
        vault = self.vault_dir(identity_id).resolve()
        if not resolved.is_relative_to(vault):
            return False
        relative = resolved.relative_to(vault)
        if relative.as_posix() in (IDENTITY_FILE, USER_FILE, CORE_FILE):
            return True
        return (
            len(relative.parts) == 2
            and relative.parts[0] == "daily"
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", relative.parts[1]) is not None
        )

    def read_entries(self, path: Path) -> list[Entry]:
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        entries: list[Entry] = []
        for line_no, line in enumerate(text.splitlines(), 1):
            entry = parse_line(line, line_no)
            if entry is not None:
                entries.append(entry)
        return entries

    def append(
        self,
        path: Path,
        content: str,
        meta: dict[str, str] | None = None,
        *,
        expected_file_hash: str | None = None,
    ) -> Entry:
        metadata = dict(meta or {})
        metadata.setdefault("id", str(uuid4()))
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(path):
            self.ensure_dir()
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if expected_file_hash is not None and file_hash(current) != expected_file_hash:
                raise RuntimeError("记忆文件已被并发修改")
            entries = self.read_entries(path)
            next_line = max((entry.line_end for entry in entries), default=0) + 1
            line = _format_line(content, metadata)
            self._append_line(path, line)
            return Entry(
                content=normalize(content),
                meta=metadata,
                line_start=next_line,
                line_end=next_line,
            )

    def remove(self, path: Path, index: int) -> None:
        with self._lock_for(path):
            entries = self.read_entries(path)
            if not (0 <= index < len(entries)):
                raise IndexError("记忆条目不在文件中")
            del entries[index]
            self._write_entries(path, entries)

    def index_by_hash(self, path: Path, target_hash: str) -> int | None:
        for index, entry in enumerate(self.read_entries(path)):
            if entry.hash == target_hash:
                return index
        return None

    def index_by_id(self, path: Path, entry_id: str) -> int | None:
        for index, entry in enumerate(self.read_entries(path)):
            if entry.id == entry_id:
                return index
        return None

    def remove_by_id(
        self,
        path: Path,
        entry_id: str,
        *,
        expected_file_hash: str | None = None,
    ) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(path):
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if expected_file_hash is not None and file_hash(current) != expected_file_hash:
                raise RuntimeError("记忆文件已被并发修改")
            entries = self.read_entries(path)
            index = next((i for i, entry in enumerate(entries) if entry.id == entry_id), None)
            if index is None:
                return False
            del entries[index]
            self._write_entries(path, entries)
            return True

    def replace_by_id(
        self,
        path: Path,
        entry_id: str,
        content: str,
        meta: dict[str, str],
        *,
        expected_file_hash: str | None = None,
    ) -> Entry:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(path):
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if expected_file_hash is not None and file_hash(current) != expected_file_hash:
                raise RuntimeError("记忆文件已被并发修改")
            entries = self.read_entries(path)
            index = next((i for i, entry in enumerate(entries) if entry.id == entry_id), None)
            if index is None:
                raise ValueError("记忆条目不在文件中")
            replacement = Entry(
                content=normalize(content),
                meta=dict(meta),
                line_start=entries[index].line_start,
                line_end=entries[index].line_end,
            )
            entries[index] = replacement
            self._write_entries(path, entries)
            return replacement

    def remove_by_hash(self, path: Path, target_hash: str) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_for(path):
            entries = self.read_entries(path)
            index = next(
                (i for i, entry in enumerate(entries) if entry.hash == target_hash),
                None,
            )
            if index is None:
                return False
            del entries[index]
            self._write_entries(path, entries)
            return True

    def _write_entries(self, path: Path, entries: list[Entry]) -> None:
        text = "".join(_format_line(entry.content, entry.meta) + "\n" for entry in entries)
        self._atomic_write(path, text)

    def _append_line(self, path: Path, line: str) -> None:
        self.ensure_dir()
        if not path.exists():
            text = line + "\n"
        else:
            current = path.read_text(encoding="utf-8")
            text = current + ("" if current.endswith("\n") else "\n") + line + "\n"
        self._atomic_write(path, text)

    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".memory-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
