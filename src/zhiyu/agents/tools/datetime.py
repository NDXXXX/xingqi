"""当前日期时间工具。"""

from datetime import datetime

from .base import AgentTool


class DateTimeTool(AgentTool):
    name = "datetime"
    description = "获取当前日期和时间。"
    schema = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": "可选，strftime 格式，如 '%Y-%m-%d %H:%M:%S'",
            },
        },
    }

    async def execute(self, format: str | None = None) -> str:
        now = datetime.now()
        return now.strftime(format) if format else now.isoformat(timespec="seconds")
