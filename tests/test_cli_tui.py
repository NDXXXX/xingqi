"""Textual 对话界面测试（Phase A 渲染层）。"""

from textual.widgets import Input, Markdown, Static

from zhiyu.cli.tui import ChatApp


class _FakeService:
    def __init__(self, events):
        self._events = events
        self.called = False

    async def run(self, request):
        self.called = True
        for event in self._events:
            yield event


def _static_text(widget) -> str:
    return getattr(widget, "_Static__content", "") or ""


async def test_chat_app_composes():
    app = ChatApp(service=_FakeService([]))
    async with app.run_test():
        assert app.query_one("#input", Input) is not None
        assert app.query_one("#messages") is not None
        assert app.query_one("#status", Static) is not None


async def test_help_command_adds_message():
    app = ChatApp(service=_FakeService([]))
    async with app.run_test() as pilot:
        app.query_one("#input", Input).value = "/help"
        await pilot.press("enter")
        await pilot.pause()

        texts = [_static_text(w) for w in app.query("#messages Static")]
        assert any("命令：" in t for t in texts)


async def test_submit_streams_assistant_reply():
    events = [
        {"type": "chunk", "text": "你好"},
        {"type": "done", "run_id": "r1", "conversation_id": "c1", "response": "你好"},
    ]
    service = _FakeService(events)
    app = ChatApp(service=service)
    async with app.run_test() as pilot:
        app.query_one("#input", Input).value = "hi"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause()

        assert service.called is True
        assert len(app.query("#messages Markdown")) == 1
