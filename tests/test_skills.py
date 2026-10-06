"""Skills 加载与匹配测试。"""

from zhiyu.integrations.skills.loader import load_skills, parse_skill
from zhiyu.integrations.skills.registry import SkillRegistry
from zhiyu.core.tools.skills import ReadSkillTool


def _write_skill(root, name: str, md: str):
    d = root / name
    d.mkdir()
    (d / "SKILL.md").write_text(md, encoding="utf-8")
    return d


def test_parse_skill_frontmatter(tmp_path):
    d = _write_skill(
        tmp_path,
        "github-analysis",
        "---\nname: github-analysis\ndescription: 分析 GitHub 仓库\n---\n\n# 步骤\n1. 读 README",
    )
    s = parse_skill(d / "SKILL.md", "github-analysis")
    assert s.name == "github-analysis"
    assert s.description == "分析 GitHub 仓库"
    assert s.content.startswith("# 步骤")


def test_load_skills_scans_dir(tmp_path):
    _write_skill(tmp_path, "research", "---\nname: research\ndescription: 搜索研究\n---\n\n正文")
    _write_skill(tmp_path, "daily-news", "---\nname: daily-news\ndescription: 每日新闻\n---\n\n正文")
    skills = load_skills(tmp_path)
    assert {s.name for s in skills} == {"research", "daily-news"}


def test_load_skills_missing_dir(tmp_path):
    assert load_skills(tmp_path / "nope") == []


def test_registry_match(tmp_path):
    _write_skill(
        tmp_path,
        "github-analysis",
        "---\nname: github-analysis\ndescription: 分析 GitHub 仓库结构与技术栈\n---\n\n正文",
    )
    _write_skill(tmp_path, "daily-news", "---\nname: daily-news\ndescription: 生成每日新闻摘要\n---\n\n正文")
    reg = SkillRegistry(tmp_path)
    result = reg.match("帮我分析这个 GitHub 仓库")
    assert result and result[0].name == "github-analysis"


async def test_skill_body_is_loaded_only_through_tool(tmp_path):
    _write_skill(
        tmp_path,
        "research",
        "---\nname: research\ndescription: 深度研究\nrequired_tools: calculator\n---\n\n秘密步骤正文",
    )
    registry = SkillRegistry(tmp_path)
    unavailable = ReadSkillTool(registry, set())
    available = ReadSkillTool(registry, {"calculator"})

    try:
        await unavailable.execute(name="research")
    except ValueError as exc:
        assert "不可用" in str(exc)
    else:
        raise AssertionError("缺少依赖工具的 Skill 被读取")

    assert await available.execute(name="research") == "秘密步骤正文"


def test_disabled_skill_is_not_matched(tmp_path):
    _write_skill(
        tmp_path,
        "disabled",
        "---\nname: disabled\ndescription: 分析仓库\nenabled: false\n---\n\n正文",
    )
    registry = SkillRegistry(tmp_path)

    assert registry.match("帮我分析仓库") == []


def test_parse_skill_rejects_duplicate_yaml_keys(tmp_path):
    skill = _write_skill(
        tmp_path,
        "duplicate",
        "---\nname: duplicate\nname: overwritten\ndescription: bad\n---\nbody",
    )
    try:
        parse_skill(skill / "SKILL.md", "duplicate")
    except ValueError as exc:
        assert "重复字段" in str(exc)
    else:
        raise AssertionError("重复 YAML 字段应拒绝")


def test_validate_package_rejects_symlinks(tmp_path):
    from zhiyu.integrations.skills.loader import validate_package

    skill = _write_skill(tmp_path, "safe", "---\nname: safe\ndescription: safe\n---\nbody")
    (skill / "escape").symlink_to(tmp_path / "outside")
    try:
        validate_package(skill)
    except ValueError as exc:
        assert "符号链接" in str(exc)
    else:
        raise AssertionError("符号链接应拒绝")
