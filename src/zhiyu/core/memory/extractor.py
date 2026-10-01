"""Memory 提取：让模型提出受约束的新增、替换、完成或失效操作。"""

import json
import re

from zhiyu.core.providers.base import AIProvider

MEMORY_TYPES = ("profile", "preference", "goal", "fact", "relationship", "project")
MEMORY_ACTIONS = ("add", "replace", "complete", "invalidate")

_PROMPT = """你是记忆提取器。只根据“本轮用户消息”判断用户明确表达的长期稳定信息。

助手回答和历史消息只能帮助理解指代，不能作为用户事实的证据。记忆内容也不能包含仅由助手提出的推断。不要保存助手建议、猜测、引用内容、角色扮演或一次性闲聊。用户改口并表达新的稳定状态或偏好时必须 replace；例如“戒咖啡了，以后别推荐”要把“喜欢咖啡”替换为“不希望收到咖啡推荐”。只有否定旧事实而没有任何可长期保存的新信息时才 invalidate。目标或项目明确完成时标记 complete。不确定就返回 []。

新增前先比较候选旧记忆的语义：旧记忆已经表达同一信息时返回 []，即使本轮换了说法或增加“仍然、没错”等语气。每个独立事实只生成一项，不要把同一原文同时保存为多个类型；涉及用户与他人的身份关系时优先使用 relationship。

只返回 JSON 数组。每项格式：
- 新增：{{"action":"add","type":"...","content":"...","evidence":"本轮用户原文片段"}}
- 替换：{{"action":"replace","target_id":"...","type":"...","content":"...","evidence":"本轮用户原文片段"}}
- 完成：{{"action":"complete","target_id":"...","evidence":"本轮用户原文片段"}}
- 失效：{{"action":"invalidate","target_id":"...","evidence":"本轮用户原文片段"}}

type 只能是 profile / preference / goal / fact / relationship / project。只能修改候选旧记忆中的 ID。最多返回 10 项。

此前上下文：
{history}

候选旧记忆：
{memories}

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


def parse_operations(text: str) -> list[dict]:
    """严格解析操作协议；任意结构错误都会拒绝整批输出。"""
    data = _load_array(text)
    if data is None or len(data) > 10:
        return []
    operations: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            return []
        action = str(item.get("action", "")).strip().lower()
        evidence = str(item.get("evidence", "")).strip()
        if action not in MEMORY_ACTIONS or not evidence:
            return []
        operation = {"action": action, "evidence": evidence}
        if action in ("replace", "complete", "invalidate"):
            target_id = str(item.get("target_id", "")).strip()
            if not target_id:
                return []
            operation["target_id"] = target_id
        if action in ("add", "replace"):
            memory_type = str(item.get("type", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if memory_type not in MEMORY_TYPES or not content or len(content) > 500:
                return []
            operation.update(type=memory_type, content=content)
        operations.append(operation)
    return operations


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


async def extract_operations(
    provider: AIProvider,
    model: str,
    *,
    user_message: str,
    assistant_message: str,
    history: list[dict],
    memories: list[dict],
) -> list[dict]:
    prompt = _PROMPT.format(
        history=json.dumps(history[-4:], ensure_ascii=False),
        memories=json.dumps(memories, ensure_ascii=False),
        user_message=user_message,
        assistant_message=assistant_message,
    )
    response = await provider.chat(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        stream=False,
        temperature=0,
    )
    return parse_operations(response.content or "")
