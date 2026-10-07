"""Interactive chat command handling and terminal rendering."""

import json
import sys

from zhiyu.application.characters import CharacterService
from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.application.conversations import ConversationService
from zhiyu.application.memories import MemoryService
from zhiyu.cli.commands.memories import _print_memories
from zhiyu.core.recall import format_welcome
from zhiyu.core.tools.registry import default_registry

CYAN = "\033[36m"
GREEN = "\033[32m"
DIM = "\033[2m"
RED = "\033[31m"
RESET = "\033[0m"
tool_registry = default_registry()

def _tty() -> bool:
    return sys.stdout.isatty()

def _color(code: str, text: str) -> str:
    if not _tty():
        return text
    return f"{code}{text}{RESET}"

def _compact_args(args: dict) -> str:
    """工具单行摘要里的参数：单参数只取值，多参数 k=v。"""
    if not args:
        return ""
    if len(args) == 1:
        return str(next(iter(args.values())))
    return ", ".join(f"{k}={v}" for k, v in args.items())

def _format_args(args: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in args.items())

def _format_output(output) -> str:
    if isinstance(output, (dict, list)):
        return json.dumps(output, ensure_ascii=False)
    return str(output)

def _tool_lines(event: dict, verbose: str) -> list[tuple[str, str]]:
    """把 tool 事件渲染成 (文本, 颜色码) 列表。"""
    name = event.get("name", "?")
    args = event.get("input") or {}
    status = event.get("status", "completed")

    if status == "failed":
        reason = event.get("error") or "失败"
        return [(f"✗ {name}（{reason}）", RED)]

    summary = f"⚙ {name}({_compact_args(args)})" if args else f"⚙ {name}"
    lines: list[tuple[str, str]] = [(summary, DIM)]
    if verbose == "off":
        return lines
    if args:
        lines.append((f"  输入  {_format_args(args)}", DIM))
    output = event.get("output")
    if output is not None:
        out_str = _format_output(output)
        limit = 4000 if verbose == "full" else 200
        if len(out_str) > limit:
            out_str = out_str[:limit] + "……截断"
        lines.append((f"  输出  {out_str}", DIM))
    return lines

async def _send(
    service: ChatService,
    text: str,
    *,
    conversation_id: str | None,
    provider_id: str | None,
    model: str | None,
    show_tools: bool = True,
    verbose: str = "off",
) -> str:
    next_conversation = conversation_id
    if show_tools:
        print(_color(GREEN, "知语> "), end="", flush=True)
    tools_shown = False
    chunk_started = False
    multiline = False
    async for event in service.run(
        ChatRequest(
            message=text,
            conversation_id=conversation_id,
            provider_id=provider_id,
            model=model,
        )
    ):
        if event["type"] == "tool" and show_tools:
            if not tools_shown:
                print()
            tools_shown = True
            for line, color in _tool_lines(event, verbose):
                print("  " + _color(color, line), flush=True)
        elif event["type"] == "chunk":
            if not chunk_started:
                if show_tools and tools_shown:
                    print(_color(GREEN, "知语> "), end="", flush=True)
                chunk_started = True
            if "\n" in event["text"]:
                multiline = True
            print(event["text"], end="", flush=True)
        elif event["type"] == "done":
            next_conversation = event["conversation_id"]
    print()
    if show_tools and not multiline:
        print()
    if next_conversation is None:
        raise RuntimeError("聊天未返回会话 ID")
    return next_conversation

def _history(conversation_id: str | None) -> None:
    if conversation_id is None:
        print("当前还没有会话")
        return
    for message in (ConversationService().history(conversation_id) or [])[-20:]:
        name = "你" if message["role"] == "user" else "知语"
        print(f"{name}> {message['content']}")

def _set_character(service: CharacterService, conversation_id: str | None, character_id: str) -> None:
    if conversation_id is None:
        raise ValueError("请先发送消息创建会话")
    service.assign_to_conversation(conversation_id, character_id)

def _show_character(service: CharacterService, conversation_id: str | None) -> None:
    if conversation_id is None:
        print("当前还没有会话")
        return
    character = service.current_for_conversation(conversation_id)
    if character is None:
        print("当前未选择角色")
        return
    print(f"当前角色：{character.name} [{character.id}]")

def _entry_state(args) -> tuple[str | None, str | None, list[str]]:
    """解析启动状态：conversation_id、续接标题、进行中事项。"""
    return ConversationService().local_entry_state(args.conversation)

def _chat_tui(args) -> None:
    from zhiyu.cli.tui import ChatApp

    conversation_id, continuing_title, goals = _entry_state(args)
    ChatApp(
        conversation_id=conversation_id,
        provider_id=args.provider,
        model=args.model,
        continuing_title=continuing_title,
        goals=goals,
    ).run()

async def _chat_line(args) -> None:
    service = ChatService()
    service.memory_processor.kick()
    characters = CharacterService()
    memories = MemoryService()
    if args.message:
        await _send(
            service,
            args.message,
            conversation_id=args.conversation,
            provider_id=args.provider,
            model=args.model,
            show_tools=False,
        )
        return

    conversation_id, continuing_title, goals = _entry_state(args)
    provider_id = args.provider
    model = args.model
    verbose = "off"
    welcome = format_welcome(continuing_title, goals)
    if welcome:
        print(welcome)
    else:
        print("知语 CLI。输入 /help 查看命令，/exit 退出。")
    first_turn = True
    while True:
        try:
            text = input(_color(CYAN, "你> ")).strip()
        except EOFError:
            print()
            return
        if not text:
            continue
        if first_turn and goals and text.isdigit() and 1 <= int(text) <= len(goals):
            text = f"跟进：{goals[int(text) - 1]}"
        if text == "/exit":
            return
        if text == "/help":
            print("/new /history /model [name] /character [id] /memory /remember <type> <content> /forget <id> /verbose [on|full|off] /tools /clear /exit")
            continue
        if text == "/new":
            conversation_id = None
            print("已开始新会话")
            continue
        if text == "/history":
            _history(conversation_id)
            continue
        if text.startswith("/model"):
            value = text.removeprefix("/model").strip()
            if value:
                model = value
                print(f"当前模型覆盖为 {model}")
            else:
                print(model or "使用默认模型")
            continue
        if text == "/character":
            _show_character(characters, conversation_id)
            continue
        if text.startswith("/character "):
            _set_character(characters, conversation_id, text.removeprefix("/character ").strip())
            print("角色已切换")
            continue
        if text == "/memory":
            _print_memories(memories.list())
            continue
        if text.startswith("/remember "):
            parts = text.removeprefix("/remember ").strip().split(maxsplit=1)
            if len(parts) != 2:
                print("用法：/remember <type> <content>", file=sys.stderr)
            else:
                item = memories.add(type=parts[0], content=parts[1])
                print(f"已记住 {item.content} [{item.id}]")
            continue
        if text.startswith("/forget "):
            memory_id = text.removeprefix("/forget ").strip()
            memories.forget(memory_id)
            print(f"已删除记忆 {memory_id}；历史聊天未删除")
            continue
        if text == "/tools":
            for tool in tool_registry.all():
                print(f"{tool.name}: {tool.description}")
            continue
        if text.startswith("/verbose"):
            value = text.removeprefix("/verbose").strip()
            if value in ("on", "full", "off"):
                verbose = value
                print(f"verbose={value}")
            else:
                print("用法：/verbose on|full|off", file=sys.stderr)
            continue
        if text == "/clear":
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            else:
                print()
            continue
        if text.startswith("/"):
            print("未知命令，输入 /help 查看可用命令", file=sys.stderr)
            continue
        first_turn = False
        conversation_id = await _send(
            service,
            text,
            conversation_id=conversation_id,
            provider_id=provider_id,
            model=model,
            show_tools=True,
            verbose=verbose,
        )
