"""Character 系统提示词组装。"""

def build_system_prompt(character) -> str:
    """有自定义 system_prompt 用自定义，否则按字段拼接 persona。"""
    if character.system_prompt and character.system_prompt.strip():
        return character.system_prompt.strip()
    parts: list[str] = []
    if character.name:
        parts.append(f"你是{character.name}。")
    if character.description:
        parts.append(character.description.strip())
    if character.personality:
        parts.append(f"性格：{character.personality.strip()}")
    if character.background:
        parts.append(f"背景：{character.background.strip()}")
    if character.speaking_style:
        parts.append(f"说话风格：{character.speaking_style.strip()}")
    return "\n".join(parts)
