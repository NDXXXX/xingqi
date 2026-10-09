"""Skill Registry：注册 / 列表 / 匹配（bigram 重叠打分）。"""

from collections.abc import Iterable
from dataclasses import replace
from sqlalchemy import select
from zhiyu.infrastructure.database.models import CharacterSkill
import logging
from pathlib import Path

from zhiyu.infrastructure.config.settings import settings
from .loader import Skill, load_skills

logger = logging.getLogger(__name__)


def _bigrams(text: str) -> set[str]:
    s = "".join(text.split()).lower()
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


class SkillRegistry:
    def __init__(self, skills_dir: Path | Iterable[Path]):
        self.skills_dirs = [skills_dir] if isinstance(skills_dir, Path) else list(skills_dir)
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self, enabled_overrides: dict[str, bool] | None = None) -> list[Skill]:
        skills: dict[str, Skill] = {}
        for skills_dir in self.skills_dirs:
            for skill in load_skills(skills_dir):
                if skill.name in skills:
                    logger.warning("Ignoring duplicate Skill name %s from %s", skill.name, skill.path)
                    continue
                if enabled_overrides and skill.name in enabled_overrides:
                    skill.enabled = enabled_overrides[skill.name]
                skills[skill.name] = skill
        self._skills = skills
        return self.all()

    def for_agent(self, db, character_id: str | None, tool_names: set[str] | None = None):
        view = SkillRegistry([])
        if character_id is None:
            skills = self.available(tool_names)
        else:
            names = set(db.scalars(select(CharacterSkill.skill_name).where(
                CharacterSkill.character_id == character_id, CharacterSkill.enabled.is_(True),
            )))
            skills = [replace(skill, enabled=True) for skill in self.all()
                      if skill.name in names and set(skill.required_tools) <= (tool_names or set())]
        view._skills = {skill.name: skill for skill in skills}
        return view

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def available(self, tool_names: set[str] | None = None) -> list[Skill]:
        tools = tool_names or set()
        return [
            skill
            for skill in self._skills.values()
            if skill.enabled and set(skill.required_tools) <= tools
        ]

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def match(self, query: str, top_k: int = 3, tool_names: set[str] | None = None) -> list[Skill]:
        q = _bigrams(query)
        if not q:
            return []
        scored: list[tuple[int, Skill]] = []
        for s in self.available(tool_names):
            overlap = len(q & _bigrams(f"{s.name} {s.description}"))
            if overlap:
                scored.append((overlap, s))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [s for _, s in scored[:top_k]]


default_registry = SkillRegistry([settings.builtin_skills_dir, settings.user_skills_dir])
