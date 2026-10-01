"""Textual 对话界面（Phase A：渲染层）。"""

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Markdown, Static
from textual import on, work

from zhiyu.application.characters import CharacterService
from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.application.memories import MemoryService
from zhiyu.core.recall import format_welcome


class ChatApp(App):
    TITLE = "知语"

    CSS = """
    #messages {
        height: 1fr;
        padding: 0 1;
    }
    #status {
        height: 1;
        color: $text-muted;
    }
    #input {
        border: none;
    }
    .user {
        color: $text;
        margin: 1 0 0 0;
    }
    .tool {
        color: $text-muted;
        margin: 0 0 0 2;
    }
    """

    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        provider_id: str | None = None,
        model: str | None = None,
        service: ChatService | None = None,
        characters: CharacterService | None = None,
        memories: MemoryService | None = None,
        continuing_title: str | None = None,
        goals: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._conversation_id = conversation_id
        self._provider_id = provider_id
        self._model = model
        self._service = service or ChatService()
        self._characters = characters or CharacterService()
        self._memories = memories or MemoryService()
        self._verbose = "off"
        self._continuing_title = continuing_title
        self._goals = goals or []
        self._first_turn = True

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="messages")
        yield Static(id="status")
        yield Input(placeholder="输入消息，/help 查看命令", id="input")

    async def on_mount(self) -> None:
        self._service.memory_processor.kick()
        self.query_one("#input", Input).focus()
        self._set_status("idle")
        welcome = format_welcome(self._continuing_title, self._goals)
        if welcome:
            await self._add(Static(welcome))
        else:
            await self._add(Static("输入消息开始对话（/help 查看命令）"))

    def _set_status(self, state: str) -> None:
        model = self._model or "默认模型"
        conv = self._conversation_id or "新会话"
        short = conv[:8] if len(conv) > 8 else conv
        self.query_one("#status", Static).update(f"{state} · {model} · 会话 #{short}")

    async def _add(self, widget) -> None:
        messages = self.query_one("#messages", VerticalScroll)
        await messages.mount(widget)
        messages.scroll_end(animate=False)

    @on(Input.Submitted)
    async def _on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        text = self._resolve_action(text)
        if text.startswith("/"):
            await self._command(text)
        else:
            self._first_turn = False
            await self._user_turn(text)

    def _resolve_action(self, text: str) -> str:
        if (
            self._first_turn
            and self._goals
            and text.isdigit()
            and 1 <= int(text) <= len(self._goals)
        ):
            return f"跟进：{self._goals[int(text) - 1]}"
        return text

    async def _command(self, text: str) -> None:
        if text == "/exit":
            self.exit()
        elif text == "/help":
            await self._add(Static("命令：/new /history /model [name] /character [id] /memory /remember <type> <content> /forget <id> /verbose [on|full|off] /tools /clear /exit"))
        elif text == "/new":
            self._conversation_id = None
            await self._add(Static("已开始新会话"))
            self._set_status("idle")
        elif text == "/clear":
            self.query_one("#messages", VerticalScroll).remove_children()
        elif text.startswith("/verbose"):
            value = text.removeprefix("/verbose").strip()
            if value in ("on", "full", "off"):
                self._verbose = value
                await self._add(Static(f"verbose={value}"))
            else:
                await self._add(Static("用法：/verbose on|full|off"))
        elif text.startswith("/model"):
            value = text.removeprefix("/model").strip()
            if value:
                self._model = value
                await self._add(Static(f"当前模型覆盖为 {value}"))
            else:
                await self._add(Static(self._model or "使用默认模型"))
        elif text == "/tools":
            from zhiyu.core.tools.registry import default_registry

            lines = [f"{t.name}: {t.description}" for t in default_registry().all()]
            await self._add(Static("\n".join(lines)))
        elif text == "/history":
            await self._add(Static(self._history_text()))
        elif text == "/character":
            await self._add(Static(self._character_text()))
        elif text.startswith("/character "):
            cid = text.removeprefix("/character ").strip()
            try:
                if self._conversation_id is None:
                    await self._add(Static("请先发送消息创建会话"))
                else:
                    self._characters.assign_to_conversation(self._conversation_id, cid)
                    await self._add(Static("角色已切换"))
            except ValueError as exc:
                await self._add(Static(f"错误：{exc}"))
        elif text == "/memory":
            items = self._memories.list()
            content = "\n".join(
                f"[{item.id}] {item.type}/{item.status} {item.content}" for item in items
            ) or "尚无记忆"
            await self._add(Static(content))
        elif text.startswith("/remember "):
            parts = text.removeprefix("/remember ").strip().split(maxsplit=1)
            if len(parts) != 2:
                await self._add(Static("用法：/remember <type> <content>"))
            else:
                try:
                    item = self._memories.add(type=parts[0], content=parts[1])
                    await self._add(Static(f"已记住 {item.content} [{item.id}]"))
                except ValueError as exc:
                    await self._add(Static(f"错误：{exc}"))
        elif text.startswith("/forget "):
            memory_id = text.removeprefix("/forget ").strip()
            try:
                self._memories.forget(memory_id)
                await self._add(Static(f"已删除记忆 {memory_id}；历史聊天未删除"))
            except ValueError as exc:
                await self._add(Static(f"错误：{exc}"))
        else:
            await self._add(Static(f"未知命令：{text}"))

    def _history_text(self) -> str:
        if self._conversation_id is None:
            return "当前还没有会话"
        from zhiyu.infrastructure.database.db import SessionLocal
        from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository

        with SessionLocal() as db:
            messages = MessageRepository().list_by_conversation(db, self._conversation_id)
        return "\n".join(
            f"{'你' if m.role == 'user' else '知语'}> {m.content}" for m in messages[-20:]
        )

    def _character_text(self) -> str:
        if self._conversation_id is None:
            return "当前还没有会话"
        character = self._characters.current_for_conversation(self._conversation_id)
        return f"当前角色：{character.name} [{character.id}]" if character else "当前未选择角色"

    async def _user_turn(self, text: str) -> None:
        await self._add(Static(f"[bold]你[/bold] {text}", classes="user"))
        self._stream(text)

    @work(exclusive=True)
    async def _stream(self, text: str) -> None:
        from zhiyu.cli.main import RED, _tool_lines

        messages = self.query_one("#messages", VerticalScroll)
        tools = Static("", classes="tool")
        md = Markdown("")
        await messages.mount(tools)
        await messages.mount(md)
        messages.scroll_end(animate=False)

        self._set_status("generating")
        final = ""
        tool_markup: list[str] = []
        try:
            async for event in self._service.run(
                ChatRequest(
                    message=text,
                    conversation_id=self._conversation_id,
                    provider_id=self._provider_id,
                    model=self._model,
                )
            ):
                if event["type"] == "tool":
                    for line, color in _tool_lines(event, self._verbose):
                        tag = "red" if color == RED else "dim"
                        tool_markup.append(f"[{tag}]{line}[/{tag}]")
                    tools.update("\n".join(tool_markup))
                    self._set_status("tool")
                elif event["type"] == "chunk":
                    final += event["text"]
                    md.update(final)
                elif event["type"] == "done":
                    self._conversation_id = event["conversation_id"]
            if not final:
                final = "（无回复）"
            md.update(final)
        except Exception as exc:
            md.update(f"运行失败：{exc}")
        finally:
            messages.scroll_end(animate=False)
            self._set_status("idle")
