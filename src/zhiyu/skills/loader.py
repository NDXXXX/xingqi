"""Safe parsing for SKILL.md manifests and their instruction text."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)
MAX_SKILL_FILE_BYTES = 1024 * 1024
MAX_PACKAGE_BYTES = 10 * 1024 * 1024
MAX_PACKAGE_FILES = 500
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KNOWN_FIELDS = {"name", "description", "version", "enabled", "required_tools", "requires_bins", "permissions"}


class _UniqueKeyLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._compose_depth = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ValueError("frontmatter 不支持 YAML 别名")
        self._compose_depth += 1
        try:
            if self._compose_depth > 32:
                raise ValueError("frontmatter 嵌套层级不能超过 32")
            return super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise ValueError("frontmatter YAML 对象键必须是标量") from exc
        if key in result:
            raise ValueError(f"frontmatter 存在重复字段：{key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    content: str
    path: Path
    enabled: bool = True
    required_tools: list[str] = field(default_factory=list)
    version: str | None = None
    requires_bins: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _string_list(value, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError(f"{field_name} 必须是字符串或字符串列表")


def parse_skill(path: Path, directory_name: str | None = None) -> Skill:
    path = Path(path)
    if path.is_symlink():
        raise ValueError("SKILL.md 不能是符号链接")
    if path.stat().st_size > MAX_SKILL_FILE_BYTES:
        raise ValueError("SKILL.md 超过 1 MiB")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"缺少 frontmatter: {path}")
    remainder = text[3:].lstrip("\r\n")
    header, separator, trailing = remainder.partition("\n---")
    if not separator:
        raise ValueError(f"frontmatter 未闭合: {path}")
    _, _, content = trailing.partition("\n")
    try:
        metadata = yaml.load(header, Loader=_UniqueKeyLoader)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"frontmatter YAML 无效: {exc}") from exc
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter 必须是 YAML 对象")
    name = metadata.get("name", directory_name or path.parent.name)
    description = metadata.get("description", "")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ValueError("Skill name 仅允许小写字母、数字和连字符，且不能以连字符开头或结尾")
    if directory_name is not None and name != directory_name:
        raise ValueError("frontmatter name 必须与 Skill 目录名一致")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Skill description 不能为空")
    version = metadata.get("version")
    if version is not None and not isinstance(version, (str, int, float)):
        raise ValueError("version 必须是字符串或数字")
    enabled = metadata.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled 必须是布尔值")
    warnings = [f"未知 frontmatter 字段：{key}" for key in metadata if key not in KNOWN_FIELDS]
    return Skill(
        name=name,
        description=description.strip(),
        content=content.lstrip("\r\n"),
        path=path,
        enabled=enabled,
        required_tools=_string_list(metadata.get("required_tools"), "required_tools"),
        version=str(version) if version is not None else None,
        requires_bins=_string_list(metadata.get("requires_bins"), "requires_bins"),
        permissions=_string_list(metadata.get("permissions"), "permissions"),
        warnings=warnings,
    )


def validate_package(path: Path) -> Skill:
    """Validate a Skill folder without following symlinks or writing files."""
    path = Path(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("Skill 来源必须是普通目录，不能是符号链接")
    total_bytes = 0
    files = 0
    skill_files: list[Path] = []
    for entry in path.rglob("*"):
        if entry.is_symlink():
            raise ValueError(f"Skill 包含符号链接：{entry.relative_to(path)}")
        if ".git" in entry.parts:
            continue
        if entry.is_file():
            files += 1
            total_bytes += entry.stat().st_size
            if files > MAX_PACKAGE_FILES:
                raise ValueError("Skill 文件数超过 500")
            if total_bytes > MAX_PACKAGE_BYTES:
                raise ValueError("Skill 包总大小超过 10 MiB")
            if entry.name == "SKILL.md":
                skill_files.append(entry)
    root_skill = path / "SKILL.md"
    if len(skill_files) != 1:
        raise ValueError("Skill 来源必须且只能包含一个 SKILL.md manifest")
    if root_skill not in skill_files:
        raise ValueError("SKILL.md 必须位于 Skill 包根目录")
    return parse_skill(root_skill, path.name)


def load_skills(skills_dir: Path) -> list[Skill]:
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return []
    if skills_dir.is_symlink() or not skills_dir.is_dir():
        logger.warning("Ignoring unsafe Skills directory: %s", skills_dir)
        return []
    result: list[Skill] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if skill_dir.name.startswith(".") or not skill_dir.is_dir() or skill_dir.is_symlink():
            continue
        manifest = skill_dir / "SKILL.md"
        if not manifest.is_file():
            continue
        try:
            validate_package(skill_dir)
            result.append(parse_skill(manifest, skill_dir.name))
        except (OSError, UnicodeError, ValueError) as exc:
            logger.warning("Ignoring invalid Skill %s: %s", skill_dir.name, exc)
    return result
