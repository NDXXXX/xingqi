"""Skills 加载与匹配测试。"""

from zhiyu.integrations.skills.loader import load_skills, parse_skill
from zhiyu.integrations.skills.registry import SkillRegistry


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
