import hashlib
import json
import sqlite3
import zipfile

import pytest

from zhiyu.application.data_archive import DataArchiveService


def _database(path):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE notes (value TEXT)")
        db.execute("INSERT INTO notes VALUES ('保留的数据')")


def test_data_backup_restores_database_memory_and_avatar_to_new_directory(tmp_path):
    source = tmp_path / "live"
    (source / "memory" / "identities" / "user").mkdir(parents=True)
    (source / "avatars").mkdir()
    _database(source / "companion.db")
    (source / "memory" / "identities" / "user" / "MEMORY.md").write_text("- 记忆\n", encoding="utf-8")
    (source / "avatars" / "avatar.png").write_bytes(b"\x89PNG\r\n\x1a\nimage")
    service = DataArchiveService(source / "companion.db", source / "memory", source / "avatars")
    archive = service.create(tmp_path / "snapshot.zip")
    target = service.restore_to(archive, tmp_path / "restored")

    with sqlite3.connect(target / "companion.db") as db:
        assert db.execute("SELECT value FROM notes").fetchone()[0] == "保留的数据"
    assert (target / "memory" / "identities" / "user" / "MEMORY.md").read_text(encoding="utf-8") == "- 记忆\n"
    assert (target / "avatars" / "avatar.png").read_bytes().endswith(b"image")


def test_restore_refuses_existing_target_and_invalid_digest(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _database(source / "companion.db")
    service = DataArchiveService(source / "companion.db", source / "memory", source / "avatars")
    archive = service.create(tmp_path / "backup.zip")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="尚不存在"):
        service.restore_to(archive, existing)
    with zipfile.ZipFile(archive) as original:
        db_bytes = original.read("companion.db")
        manifest = json.loads(original.read("manifest.json"))
    manifest["files"]["companion.db"]["sha256"] = hashlib.sha256(b"wrong").hexdigest()
    corrupt = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(corrupt, "w") as output:
        output.writestr("companion.db", db_bytes)
        output.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="摘要校验失败"):
        service.restore_to(corrupt, tmp_path / "rejected")
    assert (existing / "keep.txt").read_text() == "keep"
    assert not (tmp_path / "rejected").exists()


def test_restore_rejects_path_traversal(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _database(source / "companion.db")
    service = DataArchiveService(source / "companion.db", source / "memory", source / "avatars")
    archive = service.create(tmp_path / "backup.zip")
    with zipfile.ZipFile(archive) as original:
        db_bytes = original.read("companion.db")
        manifest = json.loads(original.read("manifest.json"))
    manifest["files"]["../outside"] = {"size": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as output:
        output.writestr("companion.db", db_bytes)
        output.writestr("../outside", b"x")
        output.writestr("manifest.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="非法路径"):
        service.restore_to(unsafe, tmp_path / "unsafe-target")
    assert not (tmp_path / "outside").exists()
