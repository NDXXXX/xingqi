"""按需读取 Skill正文，避免把所有匹配内容预先注入上下文。"""

from zhiyu.integrations.skills.registry import SkillRegistry

from .base import AgentTool


class ReadSkillTool(AgentTool):
    name = "read_skill"
    description = "读取一个已列出的 Skill 的完整操作说明。"
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill 名称"},
        },
        "required": ["name"],
    }

    def __init__(self, registry: SkillRegistry, available_tools: set[str]) -> None:
        self.registry = registry
        self.available_tools = available_tools

    async def execute(self, name: str) -> str:
        skill = self.registry.get(name)
        if skill is None or skill not in self.registry.available(self.available_tools):
            raise ValueError(f"Skill 不可用: {name}")
        return skill.content
