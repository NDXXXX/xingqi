"""Portable, secret-free snapshots of local user data."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from uuid import uuid4
import zipfile
from filelock import FileLock


MAX_ARCHIVE_BYTES = 3 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100_000


class DataArchiveService:
    def __init__(self, database_path: Path | None, memory_dir: Path, avatar_dir: Path, engine=None) -> None:
        self.database_path = Path(database_path) if database_path else None
        self.memory_dir = Path(memory_dir)
        self.avatar_dir = Path(avatar_dir)
        self.engine = engine

    def create(self, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_destination = destination.resolve()
        if destination.exists():
            raise ValueError("备份目标文件已存在，为避免覆盖已拒绝操作")
        if self.database_path is not None and resolved_destination == self.database_path.resolve():
            raise ValueError("备份目标不能覆盖数据库文件")
        for source_dir in (self.memory_dir, self.avatar_dir):
            try:
                resolved_destination.relative_to(source_dir.resolve())
            except ValueError:
                continue
            raise ValueError("备份文件不能写入记忆或头像目录")
        if self.database_path is not None and not self.database_path.is_file() and self.engine is None:
            raise ValueError("数据库尚未创建，无法备份")
        with tempfile.TemporaryDirectory(prefix="zhiyu-backup-") as temporary:
            root = Path(temporary)
            database_copy = root / "companion.db"
            with sqlite3.connect(database_copy) as target:
                if self.database_path is not None and self.database_path.is_file():
                    with sqlite3.connect(self.database_path) as source:
                        source.backup(target)
                elif self.engine is not None and self.engine.dialect.name == "sqlite":
                    connection = self.engine.raw_connection()
                    try:
                        connection.driver_connection.backup(target)
                    finally:
                        connection.close()
                else:
                    raise ValueError("数据库尚未创建，无法备份")
            files = {"companion.db": database_copy}
            self._copy_tree(self.memory_dir, root / "memory", "memory", files, lock_files=True)
            self._copy_tree(self.avatar_dir, root / "avatars", "avatars", files)
            manifest = {
                "format": "zhiyu-data-archive",
                "version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": {
                    name: {"size": path.stat().st_size, "sha256": self._digest(path)}
                    for name, path in sorted(files.items())
                },
            }
            with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, path in sorted(files.items()):
                    archive.write(path, name)
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return destination

    def restore_to(self, archive_path: Path, target: Path) -> Path:
        archive_path, target = Path(archive_path), Path(target).expanduser().absolute()
        if target.exists() or target.is_symlink():
            raise ValueError("恢复目标必须是尚不存在的目录；当前数据不会被覆盖")
        if not archive_path.is_file():
            raise ValueError("备份文件不存在")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.parent / f".{target.name}.restore-{uuid4().hex}"
        staging.mkdir(mode=0o700)
        try:
            self._extract_verified(archive_path, staging)
            self._validate_database(staging / "companion.db")
            staging.rename(target)
            return target
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    @staticmethod
    def _copy_tree(
        source: Path, destination: Path, prefix: str, files: dict[str, Path], *, lock_files: bool = False
    ) -> None:
        if not source.exists():
            return
        if source.is_symlink():
            raise ValueError(f"备份目录不能是符号链接：{prefix}")
        for item in source.rglob("*"):
            if item.name.endswith(".lock"):
                continue
            if item.is_symlink():
                raise ValueError(f"备份内容不能包含符号链接：{item.relative_to(source)}")
            if not item.is_file():
                continue
            relative = item.relative_to(source).as_posix()
            name = f"{prefix}/{relative}"
            copy = destination / relative
            copy.parent.mkdir(parents=True, exist_ok=True)
            if lock_files:
                with FileLock(str(item.parent / f".{item.name}.lock"), timeout=10):
                    shutil.copyfile(item, copy)
            else:
                shutil.copyfile(item, copy)
            files[name] = copy

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _valid_member(name: str) -> bool:
        path = PurePosixPath(name)
        return (
            not path.is_absolute()
            and "\\" not in name
            and all(part not in {"", ".", ".."} for part in path.parts)
            and (name == "companion.db" or (len(path.parts) >= 2 and path.parts[0] in {"memory", "avatars"}))
        )

    def _extract_verified(self, archive_path: Path, destination: Path) -> None:
        try:
            if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("备份文件超过 3 GiB 限制")
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_FILES:
                    raise ValueError("备份文件条目过多")
                total = sum(item.file_size for item in entries)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("备份文件超过 3 GiB 限制")
                names = [item.filename for item in entries]
                if len(names) != len(set(names)) or "manifest.json" not in names:
                    raise ValueError("备份清单缺失或包含重复文件")
                for item in entries:
                    mode = item.external_attr >> 16
                    if item.is_dir() or (mode and (mode & 0o170000) == 0o120000):
                        raise ValueError("备份不允许目录条目或符号链接")
                    if item.filename != "manifest.json" and not self._valid_member(item.filename):
                        raise ValueError("备份包含非法路径")
                manifest = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest, dict):
                    raise ValueError("备份清单格式无效")
                if (
                    manifest.get("format") != "zhiyu-data-archive"
                    or type(manifest.get("version")) is not int
                    or manifest.get("version") != 1
                ):
                    raise ValueError("不支持的星栖备份格式")
                expected = manifest.get("files")
                if not isinstance(expected, dict) or set(names) != set(expected) | {"manifest.json"}:
                    raise ValueError("备份清单与文件不一致")
                for name, metadata in expected.items():
                    if (
                        not isinstance(name, str)
                        or not self._valid_member(name)
                        or not isinstance(metadata, dict)
                        or set(metadata) != {"size", "sha256"}
                        or type(metadata.get("size")) is not int
                        or metadata["size"] < 0
                        or not isinstance(metadata.get("sha256"), str)
                    ):
                        raise ValueError("备份清单包含非法路径")
                    info = archive.getinfo(name)
                    if info.file_size != metadata.get("size"):
                        raise ValueError(f"备份文件大小校验失败：{name}")
                    digest = hashlib.sha256()
                    output = destination.joinpath(*PurePosixPath(name).parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, output.open("xb") as target:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                            target.write(block)
                    if digest.hexdigest() != metadata.get("sha256"):
                        raise ValueError(f"备份文件摘要校验失败：{name}")
                if "companion.db" not in expected:
                    raise ValueError("备份缺少数据库")
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, OSError) as exc:
            if isinstance(exc, OSError) and str(exc).startswith("[Errno 17]"):
                raise ValueError("备份包含重复路径") from exc
            raise ValueError("备份文件无效或已损坏") from exc

    @staticmethod
    def _validate_database(path: Path) -> None:
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise ValueError("备份数据库完整性检查失败")
        except sqlite3.Error as exc:
            raise ValueError("备份数据库无效") from exc
