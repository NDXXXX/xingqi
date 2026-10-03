"""文件权威的记忆存储：内容存 Markdown 文件，行级可寻址，支持原子写与乐观并发。

文件布局（``settings.memory_dir`` 下）：
- ``USER.md``   用户模型（profile / preference）
- ``MEMORY.md`` 长期核心（fact / relationship / project / goal）
- ``YYYY-MM-DD.md`` 情景日记（每日观察）
- ``DREAMS.md`` 巩固审查日志

每行一条记忆，元数据用行尾 HTML 注释承载：``- 内容 <!-- type=..., importance=... -->``。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from zhiyu.infrastructure.config.settings import settings

USER_FILE = "USER.md"
CORE_FILE = "MEMORY.md"
DREAMS_FILE = "DREAMS.md"

# 进入用户模型文件的类型；其余核心类型进入 MEMORY.md。
_USER_TYPES = ("profile", "preference")

_META_RE = re.compile(r"\s*<!--\s*(.*?)\s*-->\s*$")


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
    """把单行解析为 Entry；空行或无法识别的行返回 None。"""
    body = re.sub(r"^\s*[-*]\s+", "", line, count=1)
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
        self.lock = FileLock(str(self.dir / ".memory.lock"))

    def ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    @property
    def user_path(self) -> Path:
        return self.dir / USER_FILE

    @property
    def core_path(self) -> Path:
        return self.dir / CORE_FILE

    def daily_path(self, when: datetime | None = None) -> Path:
        return self.dir / f"{(when or datetime.now(timezone.utc)).strftime('%Y-%m-%d')}.md"

    def path_for(self, memory_type: str) -> Path:
        return self.user_path if memory_type in _USER_TYPES else self.core_path

    def list_memory_files(self) -> list[Path]:
        """返回参与记忆的 Markdown 文件（USER、MEMORY 与所有日记，排除 DREAMS）。"""
        files = [self.user_path, self.core_path]
        if self.dir.exists():
            for path in sorted(self.dir.glob("*.md")):
                if path.name not in (USER_FILE, CORE_FILE, DREAMS_FILE):
                    files.append(path)
        return files

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

    def append(self, path: Path, content: str, meta: dict[str, str] | None = None) -> Entry:
        with self.lock:
            self.ensure_dir()
            entries = self.read_entries(path)
            next_line = max((entry.line_end for entry in entries), default=0) + 1
            line = _format_line(content, meta or {})
            self._append_line(path, line)
            return Entry(
                content=normalize(content),
                meta=meta or {},
                line_start=next_line,
                line_end=next_line,
            )

    def remove(self, path: Path, index: int) -> None:
        with self.lock:
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

    def remove_by_hash(self, path: Path, target_hash: str) -> bool:
        index = self.index_by_hash(path, target_hash)
        if index is None:
            return False
        self.remove(path, index)
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
