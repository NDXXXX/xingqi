"""Skill 加载：扫描目录、解析 SKILL.md 的 frontmatter 与正文。"""

from pathlib import Path

from pydantic import BaseModel, Field


class Skill(BaseModel):
    name: str
    description: str
    content: str
    path: str
    enabled: bool = True
    required_tools: list[str] = Field(default_factory=list)


def parse_skill(skill_md: Path, fallback_name: str) -> Skill:
    text = skill_md.read_text(encoding="utf-8")
    name = fallback_name
    description = ""
    enabled = True
    required_tools: list[str] = []
    body = text.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if key == "name":
                        name = value
                    elif key == "description":
                        description = value
                    elif key == "enabled":
                        enabled = value.lower() not in {"false", "no", "0", "off"}
                    elif key == "required_tools":
                        required_tools = [item.strip() for item in value.split(",") if item.strip()]
    return Skill(
        name=name,
        description=description,
        content=body,
        path=str(skill_md.parent),
        enabled=enabled,
        required_tools=required_tools,
    )


def load_skills(skills_dir: Path) -> list[Skill]:
    if not skills_dir.is_dir():
        return []
    skills: list[Skill] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        skills.append(parse_skill(skill_md, entry.name))
    return skills
