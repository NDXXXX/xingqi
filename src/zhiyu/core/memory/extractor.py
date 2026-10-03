"""情景观察提取：让模型从本轮用户消息中提取受约束的观察，供后台巩固晋升为长期核心。"""

import json
import re

from zhiyu.core.providers.base import AIProvider

MEMORY_TYPES = ("profile", "preference", "goal", "fact", "relationship", "project")
MAX_OBSERVATIONS = 5

_OBSERVATION_PROMPT = """你是情景记忆提取器。只根据“本轮用户消息”判断用户明确表达、可能具有长期价值的信息，整理成若干条观察。

助手回答和历史消息只能帮助理解指代，不能作为用户事实的证据。不要保存助手建议、猜测、引用内容、角色扮演或一次性闲聊；不要保存已经从记忆中召回的内容。不确定就返回 []。每个独立事实只生成一项，不要把同一原文同时保存为多个类型；涉及用户与他人的身份关系时优先使用 relationship。

只返回 JSON 数组，最多 5 项。每项格式：
{{"type":"...","content":"...","evidence":"本轮用户原文片段"}}

type 只能是 profile / preference / goal / fact / relationship / project。evidence 必须是本轮用户消息里的原文片段。

此前上下文：
{history}

本轮用户消息：
{user_message}

本轮助手回答（仅供理解，不能作为证据）：
{assistant_message}"""


def _strip_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text


def _load_array(text: str) -> list | None:
    if not text:
        return None
    cleaned = _strip_fences(text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, list) else None


def parse_observations(text: str) -> list[dict]:
    """严格解析观察协议；任意结构错误都会拒绝整批输出。"""
    data = _load_array(text)
    if data is None or len(data) > MAX_OBSERVATIONS:
        return []
    observations: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            return []
        memory_type = str(item.get("type", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if memory_type not in MEMORY_TYPES or not content or not evidence or len(content) > 500:
            return []
        observations.append({"type": memory_type, "content": content, "evidence": evidence})
    return observations


def parse_candidates(text: str) -> list[dict]:
    """兼容早期仅包含 type/content 的解析接口。"""
    data = _load_array(text)
    if data is None:
        return []
    result: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if memory_type in MEMORY_TYPES and content:
            result.append({"type": memory_type, "content": content})
    return result


async def extract_observations(
    provider: AIProvider,
    model: str,
    *,
    user_message: str,
    assistant_message: str,
    history: list[dict],
) -> list[dict]:
    prompt = _OBSERVATION_PROMPT.format(
        history=json.dumps(history[-4:], ensure_ascii=False),
        user_message=user_message,
        assistant_message=assistant_message,
    )
    response = await provider.chat(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        stream=False,
        temperature=0,
    )
    return parse_observations(response.content or "")
