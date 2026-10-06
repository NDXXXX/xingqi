"""CLI 对话渲染测试（工具卡片、颜色、打印模型）。"""

from zhiyu.cli.commands import chat as cli


def test_tool_lines_off_is_single_line():
    lines = cli._tool_lines(
        {"name": "calculator", "status": "completed", "input": {"expression": "123 * 456"}, "output": 56088},
        "off",
    )

    assert lines == [("⚙ calculator(123 * 456)", cli.DIM)]


def test_tool_lines_on_expands_input_output():
    lines = cli._tool_lines(
        {"name": "calculator", "status": "completed", "input": {"expression": "123 * 456"}, "output": 56088},
        "on",
    )

    assert lines[0] == ("⚙ calculator(123 * 456)", cli.DIM)
    assert lines[1] == ("  输入  expression=123 * 456", cli.DIM)
    assert lines[2] == ("  输出  56088", cli.DIM)


def test_tool_lines_failed_is_red_with_reason():
    lines = cli._tool_lines({"name": "weather", "status": "failed", "error": "未知工具"}, "off")

    assert lines == [("✗ weather（未知工具）", cli.RED)]


def test_tool_lines_on_truncates_output_at_200():
    lines = cli._tool_lines(
        {"name": "t", "status": "completed", "input": {}, "output": "x" * 250},
        "on",
    )

    assert lines[1][0].endswith("……截断")
    assert "x" * 201 not in lines[1][0]


def test_tool_lines_full_truncates_at_4000():
    lines = cli._tool_lines(
        {"name": "t", "status": "completed", "input": {}, "output": "x" * 4000},
        "full",
    )

    assert lines[1][0].endswith("x" * 4000)
    assert lines[1][0].endswith("x" * 4000)


def test_color_off_when_not_tty(monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: False)

    assert cli._color(cli.GREEN, "知语> ") == "知语> "


def test_color_on_when_tty(monkeypatch):
    monkeypatch.setattr(cli, "_tty", lambda: True)

    assert cli._color(cli.GREEN, "知语> ") == "\033[32m知语> \033[0m"


class _FakeService:
    def __init__(self, events):
        self._events = events

    async def run(self, request):
        for event in self._events:
            yield event


async def test_send_renders_tool_card_and_second_prefix(capsys):
    events = [
        {"type": "tool", "name": "calculator", "status": "completed",
         "input": {"expression": "123 * 456"}, "output": 56088},
        {"type": "chunk", "text": "结果是 "},
        {"type": "chunk", "text": "56088"},
        {"type": "done", "run_id": "r1", "conversation_id": "c1", "response": "结果是 56088"},
    ]

    result = await cli._send(
        _FakeService(events), "算一下", conversation_id=None, provider_id=None, model=None,
        show_tools=True, verbose="off",
    )

    assert result == "c1"
    assert capsys.readouterr().out == "知语> \n  ⚙ calculator(123 * 456)\n知语> 结果是 56088\n\n"


async def test_send_silent_tools_in_single_shot(capsys):
    events = [
        {"type": "tool", "name": "calculator", "status": "completed",
         "input": {"expression": "1 + 1"}, "output": 2},
        {"type": "chunk", "text": "2"},
        {"type": "done", "run_id": "r1", "conversation_id": "c1", "response": "2"},
    ]

    result = await cli._send(
        _FakeService(events), "算一下", conversation_id=None, provider_id=None, model=None,
        show_tools=False,
    )

    assert result == "c1"
    assert capsys.readouterr().out == "2\n"
