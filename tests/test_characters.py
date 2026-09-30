"""Character 系统提示词组装测试。"""

from zhiyu.core.characters.prompts import build_system_prompt
from zhiyu.infrastructure.database.models import Character


def _character(**overrides) -> Character:
    fields = dict(
        id="c1",
        name="Luna",
        avatar=None,
        description="温柔、自然、偶尔毒舌",
        personality="温柔",
        background="长期 AI Companion",
        speaking_style="短句、自然",
        system_prompt=None,
        default_model_id=None,
    )
    fields.update(overrides)
    return Character(**fields)


def test_custom_system_prompt_wins():
    c = _character(system_prompt="你是 Luna，只回复英文。")
    assert build_system_prompt(c) == "你是 Luna，只回复英文。"


def test_blank_system_prompt_falls_back():
    c = _character(system_prompt="   ", name="Luna")
    assert "Luna" in build_system_prompt(c)


def test_composes_fields_when_no_custom():
    c = _character()
    prompt = build_system_prompt(c)
    assert "Luna" in prompt
    assert "温柔" in prompt
    assert "长期 AI Companion" in prompt
    assert "短句" in prompt
