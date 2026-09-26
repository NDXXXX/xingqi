"""Memory 提取：LLM 判断是否值得长期保存，输出 JSON 候选。"""

import json
import re

from ..providers.base import AIProvider

MEMORY_TYPES = ("profile", "preference", "goal", "fact", "relationship", "project")

_PROMPT = """你是记忆提取器。从下面的对话中提取值得长期记住的关于用户的稳定信息（如身份、偏好、目标、事实、关系、正在进行的项目）。不要提取琐碎的一次性闲聊。

以 JSON 数组返回，每项 {"type": "...", "content": "..."}。type 只能是以下之一：profile / preference / goal / fact / relationship / project。没有值得记住的内容则返回 []。只返回 JSON，不要任何其他文字。

对话：
{conversation}"""


def _strip_fences(text: str) -> str:
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return m.group(1) if m else text


def parse_candidates(text: str) -> list[dict]:
    """把 LLM 返回解析成候选列表，宽容处理代码围栏与 JSON 噪声。"""
    if not text:
        return []
    cleaned = _strip_fences(text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    result: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        t = str(item.get("type", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if t not in MEMORY_TYPES or not content:
            continue
        result.append({"type": t, "content": content})
    return result


async def extract_candidates(provider: AIProvider, model: str, messages: list[dict]) -> list[dict]:
    """调用 LLM 提取记忆候选。"""
    conversation = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    prompt = _PROMPT.replace("{conversation}", conversation)
    resp = await provider.chat(messages=[{"role": "user", "content": prompt}], model=model, stream=False)
    return parse_candidates(resp.content or "")
