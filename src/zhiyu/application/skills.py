"""Install, inspect and maintain user-managed Skills."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from zhiyu.infrastructure.config.settings import settings
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.integration_repository import InstalledSkillRepository
from sqlalchemy import select
from zhiyu.infrastructure.database.models import AppSetting, CharacterSkill
from zhiyu.integrations.skills.registry import SkillRegistry
from zhiyu.integrations.skills.loader import Skill, parse_skill, validate_package
from zhiyu.core.tools.registry import default_registry


SKILLS_REVISION_KEY = "skills_registry_revision"
GIT_URL_RE = re.compile(r"^https://[^/@\s]+(?:/[^\s]*)?$")


def _manifest(skill: Skill) -> dict:
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "enabled": skill.enabled,
        "required_tools": skill.required_tools,
        "requires_bins": skill.requires_bins,
        "permissions": skill.permissions,
        "warnings": skill.warnings,
    }


def _hash_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        if ".git" in item.parts:
            continue
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _select_subdir(root: Path, subdir: str) -> Path:
    requested = Path(subdir)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError("Skill 子目录路径无效")
    current = root
    for part in requested.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Skill 子目录不能经过符号链接")
    selected = current.resolve(strict=True)
    if root.resolve() not in selected.parents and selected != root.resolve():
        raise ValueError("Skill 子目录路径越界")
    return selected


def _changed_files(old: Path, new: Path) -> dict[str, list[str]]:
    def hashes(root: Path) -> dict[str, str]:
        result = {}
        for path in root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    before, after = hashes(old), hashes(new)
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "modified": sorted(name for name in before.keys() & after.keys() if before[name] != after[name]),
    }


class SkillService:
    def __init__(self, session_factory=SessionLocal, skills_dir: Path | None = None, character_id: str | None = None) -> None:
        self.session_factory = session_factory
        self.character_id = character_id
        self.skills_dir = Path(skills_dir or settings.user_skills_dir).expanduser()
        self.repo = InstalledSkillRepository()

    def validate(self, path: str | Path) -> dict:
        source = Path(path).expanduser()
        skill = validate_package(source)
        source = source.resolve(strict=True)
        return {**_manifest(skill), "content_hash": _hash_tree(source), "path": str(source)}

    def preview(self, source: str | Path, *, ref: str | None = None, subdir: str | None = None) -> dict:
        path, revision, source_type = self._materialize(source, ref=ref, subdir=subdir)
        try:
            skill = validate_package(path)
            self._assert_name_available(skill.name)
            return {
                **_manifest(skill),
                "source_type": source_type,
                "source": str(source),
                "resolved_revision": revision,
                "content_hash": _hash_tree(path),
                "files": sorted(item.relative_to(path).as_posix() for item in path.rglob("*") if item.is_file())[:500],
            }
        finally:
            if source_type == "git":
                self._cleanup_temp_source(path)

    def list(self, tool_names: set[str] | None = None) -> list[dict]:
        available_tools = set(default_registry().names()) if tool_names is None else tool_names
        metadata = {item.name: item for item in self.repo_list()}
        result = []
        # Include already-existing user Skills without moving or silently registering them.
        if self.skills_dir.exists():
            for path in sorted(self.skills_dir.iterdir()):
                if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
                    continue
                try:
                    skill = parse_skill(path / "SKILL.md", path.name)
                except (OSError, UnicodeError, ValueError) as exc:
                    row = metadata.get(path.name)
                    result.append({
                        "name": path.name,
                        "valid": False,
                        "available": False,
                        "enabled": bool(row.enabled) if row else False,
                        "error": str(exc),
                        "source_type": row.source_type if row else "local",
                        "source": row.source_locator if row else "unmanaged",
                        "path": row.installed_path if row else str(path),
                        "managed": row is not None,
                        "missing_tools": [],
                        "missing_bins": [],
                    })
                    continue
                row = metadata.get(skill.name)
                result.append(self._status(skill, row, available_tools))
        if self.character_id is not None:
            with self.session_factory() as db:
                links = {row.skill_name: row.enabled for row in db.scalars(select(CharacterSkill).where(CharacterSkill.character_id == self.character_id))}
            for skill in SkillRegistry(settings.builtin_skills_dir).all():
                result.append(self._status(skill, None, available_tools))
            for item in result:
                item["assigned"] = item["name"] in links
                item["enabled"] = links.get(item["name"], False)
                item["available"] = item["enabled"] and item.get("valid", True) and not item.get("missing_tools") and not item.get("missing_bins")
        return result

    def repo_list(self):
        with self.session_factory() as db:
            return self.repo.list(db)

    def trash_list(self) -> list[dict]:
        if self.character_id is not None:
            return []
        with self.session_factory() as db:
            return [
                {"name": item.name, "source_type": item.source_type,
                 "trashed_at": item.trashed_at.isoformat() if item.trashed_at else None}
                for item in self.repo.list(db) if item.trashed_at
            ]

    def register_existing(self) -> int:
        """Record valid pre-existing user Skills without moving or rewriting files."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        registered = 0
        with self.session_factory() as db:
            for path in sorted(self.skills_dir.iterdir()):
                if path.name.startswith(".") or not path.is_dir() or path.is_symlink():
                    continue
                if (settings.builtin_skills_dir / path.name).exists():
                    continue
                try:
                    skill = validate_package(path)
                except (OSError, UnicodeError, ValueError):
                    continue
                if self.repo.get(db, skill.name) is not None:
                    continue
                content_hash = _hash_tree(path)
                self.repo.save(
                    db,
                    name=skill.name,
                    source_type="local",
                    source_locator=str(path.resolve()),
                    source_ref=None,
                    resolved_revision=f"local:{content_hash}",
                    content_hash=content_hash,
                    installed_path=str(path.resolve()),
                    manifest_json=json.dumps(_manifest(skill), ensure_ascii=False),
                    enabled=skill.enabled,
                    trashed_at=None,
                    last_error=None,
                )
                registered += 1
            if registered:
                self._bump(db)
        return registered

    def show(self, name: str, tool_names: set[str] | None = None) -> dict:
        item = next((row for row in self.list(tool_names) if row["name"] == name), None)
        if item is None:
            raise ValueError(f"找不到 Skill：{name}")
        return item

    def install(self, source: str | Path, *, ref: str | None = None, subdir: str | None = None) -> dict:
        locator = str(source)
        if subdir and str(source).startswith("https://"):
            locator += f"#zhiyu-subdir={subdir}"
        source_path, revision, source_type = self._materialize(source, ref=ref, subdir=subdir)
        if source_type == "local":
            locator = str(source_path)
        try:
            skill = validate_package(source_path)
            self._assert_name_available(skill.name)
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            target = self.skills_dir / skill.name
            stage = self._copy_to_stage(source_path)
            try:
                os.replace(stage, target)
                self._save(skill, target, source_type, locator, ref, revision)
                if self.character_id is not None:
                    with self.session_factory() as db:
                        self.repo.get(db, skill.name).enabled = False
                        db.add(CharacterSkill(character_id=self.character_id, skill_name=skill.name, enabled=True))
                        self._bump(db)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                raise
            shutil.rmtree(stage.parent, ignore_errors=True)
            return self.show(skill.name)
        finally:
            if source_type == "git":
                self._cleanup_temp_source(source_path)

    def update(
        self, name: str, *, ref: str | None = None, apply: bool = False
    ) -> dict:
        if self.character_id is not None:
            raise ValueError("安装包更新会影响引用它的智能体，请在默认助手的 Skill 管理中更新")
        item = self._get(name)
        if item is None:
            raise ValueError("只能更新通过星栖安装并登记的 Skill")
        if item.trashed_at:
            raise ValueError("Skill 已在回收站，请先恢复")
        target = Path(item.installed_path)
        if target.name != name or target.is_symlink() or not target.is_dir() or target.parent.resolve() != self.skills_dir.resolve():
            raise ValueError("Skill 安装路径异常，拒绝更新")
        new_ref = ref or item.source_ref
        source, revision, source_type = self._materialize(item.source_locator, ref=new_ref, subdir=None)
        try:
            skill = validate_package(source)
            if skill.name != name:
                raise ValueError("更新包中的 Skill name 与已安装名称不一致")
            new_hash = _hash_tree(source)
            report = {
                "name": name,
                "old_hash": item.content_hash,
                "new_hash": new_hash,
                "old_revision": item.resolved_revision,
                "new_revision": revision,
                "changed": new_hash != item.content_hash,
                "changed_files": _changed_files(Path(item.installed_path), source),
                "old_manifest": json.loads(item.manifest_json or "{}"),
                "new_manifest": _manifest(skill),
                "applied": False,
            }
            if not apply:
                return report
            history_root = self.skills_dir / ".history" / name
            history_root.mkdir(parents=True, exist_ok=True)
            backup = history_root / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{item.content_hash[:12]}"
            shutil.copytree(target, backup)
            stage = self._copy_to_stage(source)
            old = self.skills_dir / f".{name}.old"
            if old.exists():
                shutil.rmtree(old)
            os.replace(target, old)
            try:
                os.replace(stage, target)
                self._save(skill, target, source_type, item.source_locator, new_ref, revision)
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                os.replace(old, target)
                raise
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(stage.parent, ignore_errors=True)
            self._trim_history(history_root)
            report["applied"] = True
            return report
        finally:
            if source_type == "git":
                self._cleanup_temp_source(source)

    def enable(self, name: str, enabled: bool) -> None:
        if self.character_id is not None:
            self.show(name)
            with self.session_factory() as db:
                link = db.get(CharacterSkill, (self.character_id, name))
                if link is None:
                    db.add(CharacterSkill(character_id=self.character_id, skill_name=name, enabled=enabled))
                else:
                    link.enabled = enabled
                self._bump(db)
            return
        with self.session_factory() as db:
            item = self.repo.get(db, name)
            if item is None or item.trashed_at:
                raise ValueError("找不到可管理的已安装 Skill")
            item.enabled = enabled
            self._bump(db)

    def remove(self, name: str) -> Path:
        if self.character_id is not None:
            with self.session_factory() as db:
                link = db.get(CharacterSkill, (self.character_id, name))
                if link is None:
                    raise ValueError("该智能体未关联这个 Skill")
                db.delete(link)
                self._bump(db)
            return self.skills_dir / name
        with self.session_factory() as db:
            if db.scalars(select(CharacterSkill).where(CharacterSkill.skill_name == name)).first() is not None:
                raise ValueError("其他智能体仍关联此 Skill，请先移除关联")
        item = self._get(name)
        if item is None or item.trashed_at:
            raise ValueError("只能移除星栖登记的用户 Skill")
        target = Path(item.installed_path)
        if target.is_symlink() or not target.is_dir() or target.parent.resolve() != self.skills_dir.resolve():
            raise ValueError("Skill 安装路径异常，拒绝移动")
        trash = self.skills_dir / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        destination = trash / f"{name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        os.replace(target, destination)
        try:
            with self.session_factory() as db:
                row = self.repo.get(db, name)
                manifest = json.loads(row.manifest_json or "{}")
                manifest["_trashed_enabled"] = row.enabled
                row.manifest_json = json.dumps(manifest, ensure_ascii=False)
                row.enabled = False
                row.installed_path = str(destination)
                row.trashed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                self._bump(db)
        except Exception:
            os.replace(destination, target)
            raise
        return destination

    def restore(self, name: str) -> Path:
        if self.character_id is not None:
            raise ValueError("请在默认助手的 Skill 管理中恢复安装包")
        item = self._get(name)
        if item is None or not item.trashed_at:
            raise ValueError("回收站中没有这个 Skill")
        source = Path(item.installed_path)
        if source.parent.resolve() != (self.skills_dir / ".trash").resolve() or source.is_symlink():
            raise ValueError("回收站路径异常，拒绝恢复")
        target = self.skills_dir / name
        if target.exists():
            raise ValueError("同名 Skill 已存在，无法覆盖；请先处理冲突")
        os.replace(source, target)
        try:
            with self.session_factory() as db:
                row = self.repo.get(db, name)
                manifest = json.loads(row.manifest_json or "{}")
                row.enabled = manifest.pop("_trashed_enabled", True)
                row.manifest_json = json.dumps(manifest, ensure_ascii=False)
                row.installed_path = str(target)
                row.trashed_at = None
                self._bump(db)
        except Exception:
            os.replace(target, source)
            raise
        return target

    def enabled_overrides(self) -> dict[str, bool]:
        with self.session_factory() as db:
            return {item.name: item.enabled for item in self.repo.list(db) if not item.trashed_at}

    def request_reload(self) -> None:
        self._commit_change()

    def purge_expired(self) -> int:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        removed = 0
        with self.session_factory() as db:
            for item in self.repo.list(db):
                if item.trashed_at and item.trashed_at < cutoff:
                    path = Path(item.installed_path)
                    if path.parent.resolve() == (self.skills_dir / ".trash").resolve():
                        shutil.rmtree(path, ignore_errors=True)
                    self.repo.delete(db, item.name)
                    removed += 1
            if removed:
                self._bump(db)
        return removed

    def _status(self, skill: Skill, row, tool_names: set[str]) -> dict:
        enabled = row.enabled if row else skill.enabled
        missing_tools = [name for name in skill.required_tools if name not in tool_names]
        missing_bins = [name for name in skill.requires_bins if shutil.which(name) is None]
        collision = (settings.builtin_skills_dir / skill.name).exists()
        return {
            **_manifest(skill),
            "enabled": enabled,
            "available": enabled and not missing_tools and not missing_bins and not collision,
            "collision": collision,
            "missing_tools": missing_tools,
            "missing_bins": missing_bins,
            "source_type": row.source_type if row else "local",
            "source": row.source_locator if row else "unmanaged",
            "revision": row.resolved_revision if row else None,
            "content_hash": _hash_tree(skill.path.parent),
            "registered_hash": row.content_hash if row else None,
            "modified": bool(row and _hash_tree(skill.path.parent) != row.content_hash),
            "path": row.installed_path if row else str(skill.path.parent),
            "managed": row is not None,
            "trashed": bool(row and row.trashed_at),
            "updated_at": row.updated_at.isoformat() if row else None,
        }

    def _get(self, name):
        with self.session_factory() as db:
            return self.repo.get(db, name)

    def _assert_name_available(self, name: str) -> None:
        if (settings.builtin_skills_dir / name).exists():
            raise ValueError(f"不能覆盖内置 Skill：{name}")
        if (self.skills_dir / name).exists():
            raise ValueError(f"同名 Skill 已存在：{name}")
        if self._get(name) is not None:
            raise ValueError(f"Skill {name} 已有生命周期记录；如在回收站请先恢复")

    def _materialize(self, source, *, ref: str | None, subdir: str | None):
        value = str(source)
        path = Path(value).expanduser()
        if path.exists():
            if path.is_symlink():
                raise ValueError("Skill 来源不能是符号链接")
            path = path.resolve(strict=True)
            if subdir:
                path = _select_subdir(path, subdir)
            return path, ref or _hash_tree(path), "local"
        locator, marker, stored_subdir = value.partition("#zhiyu-subdir=")
        if marker:
            subdir = subdir or stored_subdir
            value = locator
        if not GIT_URL_RE.fullmatch(value):
            raise ValueError("Git Skill 来源必须是 HTTPS 仓库 URL 或本地目录")
        parsed_url = urlsplit(value)
        if parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
            raise ValueError("Git 来源 URL 不能包含凭据、查询参数或片段")
        temp = Path(tempfile.mkdtemp(prefix="zhiyu-skill-"))
        checkout = temp / "repo"
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(temp),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
        try:
            self._git(["clone", "--no-checkout", "--filter=blob:none", "--depth=1", value, str(checkout)], env)
            target_ref = ref or "HEAD"
            self._git(["-C", str(checkout), "fetch", "--depth=1", "origin", target_ref], env)
            commit = self._git(["-C", str(checkout), "rev-parse", "FETCH_HEAD"], env).strip()
            self._git(["-C", str(checkout), "checkout", "--detach", commit], env)
            shutil.rmtree(checkout / ".git", ignore_errors=True)
            result = _select_subdir(checkout, subdir) if subdir else checkout
            return result, commit, "git"
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise

    @staticmethod
    def _git(args: list[str], env: dict[str, str]) -> str:
        try:
            result = subprocess.run(["git", *args], check=True, capture_output=True, text=True, timeout=120, env=env)
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or "Git 命令失败").strip()[-1000:]
            raise ValueError(message) from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Git 操作超时") from exc
        return result.stdout

    def _copy_to_stage(self, source: Path) -> Path:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        skill = validate_package(source)
        stage = Path(tempfile.mkdtemp(prefix=".skill-stage-", dir=self.skills_dir)) / skill.name
        shutil.copytree(source, stage, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        # Revalidate copied files to catch a source race between validation and copying.
        validate_package(stage)
        return stage

    def _save(self, skill, target, source_type, locator, source_ref, revision):
        values = dict(
            name=skill.name, source_type=source_type, source_locator=locator,
            source_ref=source_ref if source_type == "git" else None, resolved_revision=revision, content_hash=_hash_tree(target),
            installed_path=str(target), manifest_json=json.dumps(_manifest(skill), ensure_ascii=False),
            enabled=skill.enabled, trashed_at=None, last_error=None,
        )
        with self.session_factory() as db:
            self.repo.save(db, **values)
            self._bump(db)

    def _commit_change(self):
        with self.session_factory() as db:
            self._bump(db)

    def _bump(self, db):
        setting = db.get(AppSetting, SKILLS_REVISION_KEY)
        revision = json.loads(setting.value_json) if setting else 0
        payload = json.dumps(int(revision) + 1)
        if setting is None:
            db.add(AppSetting(key=SKILLS_REVISION_KEY, value_json=payload))
        else:
            setting.value_json = payload
        db.commit()

    @staticmethod
    def _trim_history(path: Path) -> None:
        versions = sorted((p for p in path.iterdir() if p.is_dir()), reverse=True)
        for old in versions[3:]:
            shutil.rmtree(old)

    @staticmethod
    def _cleanup_temp_source(path: Path) -> None:
        for parent in (path, *path.parents):
            if parent.name.startswith("zhiyu-skill-"):
                shutil.rmtree(parent, ignore_errors=True)
                return
