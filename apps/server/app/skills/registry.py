"""Skill Registry：注册 / 列表 / 匹配（bigram 重叠打分）。"""

from pathlib import Path

from ..config.settings import settings
from .loader import Skill, load_skills


def _bigrams(text: str) -> set[str]:
    s = "".join(text.split()).lower()
    if not s:
        return set()
    if len(s) == 1:
        return {s}
    return {s[i : i + 2] for i in range(len(s) - 1)}


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self.reload()

    def reload(self) -> list[Skill]:
        self._skills = {s.name: s for s in load_skills(self.skills_dir)}
        return self.all()

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def match(self, query: str, top_k: int = 3) -> list[Skill]:
        q = _bigrams(query)
        if not q:
            return []
        scored: list[tuple[int, Skill]] = []
        for s in self._skills.values():
            overlap = len(q & _bigrams(f"{s.name} {s.description}"))
            if overlap:
                scored.append((overlap, s))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [s for _, s in scored[:top_k]]


default_registry = SkillRegistry(settings.skills_dir)
