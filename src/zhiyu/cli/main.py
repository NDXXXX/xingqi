"""The ``zhiyu`` command-line entry point."""

import argparse
import asyncio
from getpass import getpass
import ipaddress
import json
import os
import socket
import subprocess
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

from zhiyu.application.channels import ChannelService
from zhiyu.application.characters import CharacterService
from zhiyu.application.chat import ChatRequest, ChatService
from zhiyu.application.doctor import run_checks
from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.application.memories import MemoryService
from zhiyu.application.memory_jobs import MemoryJobProcessor
from zhiyu.application.mcp import McpService
from zhiyu.application.skills import SkillService
from zhiyu.application.providers import ProviderService
from zhiyu.core.recall import format_welcome, last_local_conversation, list_goals
from zhiyu.core.tools.registry import default_registry
from zhiyu.infrastructure.config.logging import configure_logging
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.migrations import upgrade_database
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.cli.commands.providers import handle_provider as _provider

tool_registry = default_registry()

# 终端颜色（仅 TTY 启用）
CYAN = "\033[36m"
GREEN = "\033[32m"
DIM = "\033[2m"
RED = "\033[31m"
RESET = "\033[0m"


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhiyu", description="知语 Personal AI Agent")
    parser.add_argument("--debug", action="store_true", help="显示完整异常")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="检查本地运行环境")

    serve = sub.add_parser("serve", help="启动本地 WebUI 与 API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    chat = sub.add_parser("chat", help="启动终端聊天")
    chat.add_argument("message", nargs="?", help="发送单条消息；省略后进入交互模式")
    chat.add_argument("--conversation", help="继续指定会话")
    chat.add_argument("--provider", help="指定 Provider ID")
    chat.add_argument("--model", help="指定模型名称")

    provider = sub.add_parser("provider", help="管理模型服务")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_sub.add_parser("list", help="列出 Provider")
    provider_add = provider_sub.add_parser("add", help="添加 Provider")
    provider_add.add_argument("name")
    provider_add.add_argument("--type", required=True, dest="provider_type")
    provider_add.add_argument("--base-url")
    provider_add.add_argument("--api-key-env", help="从环境变量读取 API Key")
    provider_test = provider_sub.add_parser("test", help="测试 Provider")
    provider_test.add_argument("name")
    provider_test.add_argument("--model")
    provider_default = provider_sub.add_parser("default", help="设置默认模型")
    provider_default.add_argument("name")
    provider_default.add_argument("model")
    provider_fallback = provider_sub.add_parser("fallback", help="配置 Provider故障切换顺序")
    provider_fallback.add_argument("name", help="主 Provider名称")
    provider_fallback.add_argument("fallbacks", nargs="*", help="备用 Provider名称，留空表示清除")
    provider_vision = provider_sub.add_parser("vision", help="声明模型是否支持图片输入")
    provider_vision.add_argument("name")
    provider_vision.add_argument("model")
    provider_vision.add_argument(
        "--enabled", action=argparse.BooleanOptionalAction, default=True
    )

    character = sub.add_parser("character", help="管理角色")
    character_sub = character.add_subparsers(dest="character_command", required=True)
    character_sub.add_parser("list", help="列出角色")
    character_show = character_sub.add_parser("show", help="查看角色详情")
    character_show.add_argument("id")
    character_add = character_sub.add_parser("add", help="创建角色")
    character_add.add_argument("--name", required=True)
    character_add.add_argument("--description")
    character_add.add_argument("--personality")
    character_add.add_argument("--background")
    character_add.add_argument("--speaking-style")
    character_add.add_argument("--system-prompt", help="设置后覆盖以上字段")
    character_delete = character_sub.add_parser("delete", help="删除角色")
    character_delete.add_argument("id")

    memory = sub.add_parser("memory", help="管理本地用户记忆")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    memory_list = memory_sub.add_parser("list", help="列出记忆")
    memory_list.add_argument("--all", action="store_true", dest="include_inactive")
    memory_list.add_argument("--tier", choices=["core", "episodic"], help="按层级过滤")
    memory_search = memory_sub.add_parser("search", help="搜索记忆")
    memory_search.add_argument("query")
    memory_search.add_argument("--all", action="store_true", dest="include_inactive")
    memory_search.add_argument("--tier", choices=["core", "episodic"], help="按层级过滤")
    memory_recall_explain = memory_sub.add_parser(
        "recall-explain", help="解释一次记忆召回的候选、通道和排名"
    )
    memory_recall_explain.add_argument("query")
    memory_show = memory_sub.add_parser("show", help="查看记忆详情")
    memory_show.add_argument("id")
    memory_add = memory_sub.add_parser("add", help="手动添加记忆")
    memory_add.add_argument("--type", required=True)
    memory_add.add_argument("--content", required=True)
    memory_edit = memory_sub.add_parser("edit", help="纠正记忆")
    memory_edit.add_argument("id")
    memory_edit.add_argument("--content", required=True)
    memory_complete = memory_sub.add_parser("complete", help="完成目标或项目")
    memory_complete.add_argument("id")
    memory_forget = memory_sub.add_parser("forget", help="删除记忆")
    memory_forget.add_argument("id", nargs="?")
    memory_forget.add_argument("--conversation", dest="conversation_id", help="遗忘某会话派生的记忆")
    memory_forget.add_argument("--apply", action="store_true", help="实际执行（默认仅预览）")
    memory_sub.add_parser("status", help="显示后台提取任务状态")
    memory_sub.add_parser("sync", help="处理待执行的提取任务")
    memory_sub.add_parser("retry", help="重试失败的提取任务")
    memory_sub.add_parser("index", help="从记忆文件重建索引")
    memory_sub.add_parser("export", help="导出记忆文件内容")
    memory_consolidate = memory_sub.add_parser("consolidate", help="巩固情景观察为长期核心")
    memory_consolidate.add_argument("--apply", action="store_true", help="实际应用（默认 dry-run）")
    memory_consolidate.add_argument("--force", action="store_true", help="忽略阈值强制运行")
    consolidation = memory_sub.add_parser("consolidation", help="查看巩固记录")
    consolidation_sub = consolidation.add_subparsers(dest="consolidation_command", required=True)
    consolidation_sub.add_parser("list", help="列出巩固记录")

    qq = sub.add_parser("qq", help="管理 QQ OneBot 渠道")
    qq_sub = qq.add_subparsers(dest="qq_command", required=True)
    qq_configure = qq_sub.add_parser("configure", help="配置反向 WebSocket")
    qq_configure.add_argument("--endpoint", default="ws://127.0.0.1:6199/ws")
    qq_configure.add_argument("--token-env", help="从环境变量读取 Access Token")
    qq_configure.add_argument("--no-token", action="store_true")
    qq_configure.add_argument("--owner-user-id", help="允许使用个人 Agent 的主人 QQ 号")
    qq_configure.add_argument("--clear-owner-user-id", action="store_true")
    qq_configure.add_argument(
        "--group-messages",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="允许主人在群聊中通过 @ 使用 Agent（默认关闭）",
    )
    qq_configure.add_argument(
        "--group-require-mention",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="群聊消息是否必须 @ Agent（默认开启）",
    )
    qq_sub.add_parser("listen", help="监听 NapCat 连接")
    qq_sub.add_parser("status", help="显示持久化配置")
    qq_sub.add_parser("doctor", help="只读检查 NapCat 与 QQ 配置")
    qq_events = qq_sub.add_parser("events", help="显示最近渠道事件")
    qq_events.add_argument("--limit", type=int, default=20)
    qq_replay = qq_sub.add_parser("replay", help="重新排队失败事件")
    qq_replay.add_argument("event_id")
    qq_deliveries = qq_sub.add_parser("deliveries", help="显示最近投递")
    qq_deliveries.add_argument("--limit", type=int, default=20)
    qq_retry = qq_sub.add_parser("retry-delivery", help="重新排队失败投递")
    qq_retry.add_argument("delivery_id")
    qq_retry.add_argument(
        "--confirm-unknown",
        action="store_true",
        help="确认未知投递可能重复后仍然重试",
    )
    qq_groups = qq_sub.add_parser("groups", help="管理群聊白名单")
    qq_groups_sub = qq_groups.add_subparsers(dest="qq_groups_command", required=True)
    qq_groups_sub.add_parser("list", help="列出群策略")
    qq_group_allow = qq_groups_sub.add_parser("allow", help="允许主人在指定群使用")
    qq_group_allow.add_argument("group_id")
    qq_group_allow.add_argument(
        "--require-mention", action=argparse.BooleanOptionalAction, default=True
    )
    qq_group_allow.add_argument("--allow-tool", action="append", default=[])
    qq_group_allow.add_argument("--system-prompt")
    qq_group_deny = qq_groups_sub.add_parser("deny", help="禁用指定群")
    qq_group_deny.add_argument("group_id")

    mcp = sub.add_parser("mcp", help="管理 MCP Server")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser("list", help="列出 MCP服务器")
    mcp_sub.add_parser("doctor", help="检查已启用 MCP Server")
    mcp_add = mcp_sub.add_parser("add", help="添加或更新 MCP服务器")
    mcp_add.add_argument("first")
    mcp_add.add_argument("second", nargs="?")
    mcp_add.add_argument("--transport", choices=["stdio", "http", "streamable_http", "sse"], default=None)
    mcp_add.add_argument("--command")
    mcp_add.add_argument("--url")
    mcp_add.add_argument("--arg", action="append", default=[], help="传给服务器的参数，可重复")
    mcp_add.add_argument("--allow-tool", action="append", default=[])
    mcp_disable = mcp_sub.add_parser("disable", help="禁用 MCP服务器")
    mcp_disable.add_argument("name")
    for command in ("enable", "remove", "test", "show", "tools", "resources", "prompts", "reconnect", "logs"):
        parser_item = mcp_sub.add_parser(command)
        parser_item.add_argument("name")
        if command == "remove":
            parser_item.add_argument("--confirm", action="store_true")
        if command == "enable":
            parser_item.add_argument("--confirm-command", action="store_true")
        if command == "tools":
            parser_item.add_argument("--allow", action="append", default=[])
            parser_item.add_argument("--allow-all", action="store_true")
            parser_item.add_argument("--deny-all", action="store_true")
        if command in {"resources", "prompts"}:
            parser_item.add_argument("--allow", action="append", default=[])
            parser_item.add_argument("--deny-all", action="store_true")
    resource = mcp_sub.add_parser("resource")
    resource_sub = resource.add_subparsers(dest="mcp_resource_command", required=True)
    resource_read = resource_sub.add_parser("read")
    resource_read.add_argument("name")
    resource_read.add_argument("uri")
    prompt = mcp_sub.add_parser("prompt")
    prompt_sub = prompt.add_subparsers(dest="mcp_prompt_command", required=True)
    prompt_show = prompt_sub.add_parser("show")
    prompt_show.add_argument("name")
    prompt_show.add_argument("prompt")
    prompt_show.add_argument("--arg", action="append", default=[])
    env = mcp_sub.add_parser("env")
    env_sub = env.add_subparsers(dest="mcp_env_command", required=True)
    for env_action in ("set", "secret", "unset"):
        env_parser = env_sub.add_parser(env_action)
        env_parser.add_argument("name")
        env_parser.add_argument("key")
        if env_action == "set":
            env_parser.add_argument("value")
    auth = mcp_sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="mcp_auth_command", required=True)
    auth_set = auth_sub.add_parser("set")
    auth_set.add_argument("name")
    auth_set.add_argument("--header", default="Authorization")
    auth_set.add_argument("--bearer", action="store_true", help="将值作为 Authorization: Bearer Token 保存")
    auth_unset = auth_sub.add_parser("unset")
    auth_unset.add_argument("name")
    auth_unset.add_argument("--header", default="Authorization")

    skills = sub.add_parser("skills", help="管理本地 Skills")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    for command in ("list", "reload"):
        skills_sub.add_parser(command)
    for command in ("show", "validate", "install", "update", "diff", "enable", "disable", "remove", "restore"):
        item = skills_sub.add_parser(command)
        item.add_argument("target")
        if command in {"install", "update"}:
            item.add_argument("--ref")
            item.add_argument("--subdir")
            if command == "install":
                item.add_argument("--yes", action="store_true", help="确认安装预览")
            if command == "update":
                item.add_argument("--apply", action="store_true")
        if command == "remove":
            item.add_argument("--confirm", action="store_true")

    database = sub.add_parser("db", help="数据库维护")
    database_sub = database.add_subparsers(dest="db_command", required=True)
    database_sub.add_parser("upgrade", help="执行数据库迁移")

    dream = sub.add_parser("dream", help="运行后台记忆巩固守护")
    dream.add_argument("--interval", type=int, default=3600, help="巩固间隔秒数")
    dream.add_argument("--once", action="store_true", help="只运行一次后退出")

    embedding = sub.add_parser("embedding", help="配置语义检索的 embedding 端点")
    embedding_sub = embedding.add_subparsers(dest="embedding_command", required=True)
    embedding_configure = embedding_sub.add_parser("configure", help="配置 embedding 端点")
    embedding_configure.add_argument("--base-url", required=True)
    embedding_configure.add_argument("--model", required=True)
    embedding_configure.add_argument("--api-key-env", help="从环境变量读取 API Key")
    embedding_sub.add_parser("status", help="显示 embedding 配置状态")
    return parser


def _normalize_cli_args(argv: list[str]) -> list[str]:
    """Allow a repeated --arg value beginning with '-' without requiring '='."""
    result = list(argv)
    index = 0
    while index + 1 < len(result):
        if result[index] == "--arg" and result[index + 1].startswith("-"):
            result[index : index + 2] = [f"--arg={result[index + 1]}"]
        index += 1
    return result


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
    with SessionLocal() as db:
        messages = MessageRepository().list_by_conversation(db, conversation_id)
    for message in messages[-20:]:
        name = "你" if message.role == "user" else "知语"
        print(f"{name}> {message.content}")


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
    conversation_id = args.conversation
    continuing_title = None
    goals: list[str] = []
    with SessionLocal() as db:
        identity_id = IdentityRepository().local(db).id
        if conversation_id is None:
            last = last_local_conversation(db, identity_id)
            if last is not None:
                conversation_id = last.id
                continuing_title = last.title
        goals = list_goals(db, identity_id)
    return conversation_id, continuing_title, goals


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


async def _qq_listen(service: ChannelService) -> None:
    memory_processor = MemoryJobProcessor()
    memory_processor.kick()
    endpoint = await service.start_qq()
    print(f"正在监听 {endpoint}，等待 NapCat 连接。按 Ctrl+C 停止。")
    previous = None
    try:
        while True:
            status = service.status()["status"]
            if status != previous:
                print(f"QQ: {status}")
                previous = status
            await asyncio.sleep(0.5)
    finally:
        await service.stop()


def _character(args) -> None:
    service = CharacterService()
    if args.character_command == "list":
        characters = service.list()
        if not characters:
            print("尚未创建角色，使用 zhiyu character add 创建")
            return
        for item in characters:
            detail = " · ".join(part for part in (item.personality, item.speaking_style) if part)
            if item.has_system_prompt:
                detail = f"{detail} · 系统提示词已覆盖" if detail else "系统提示词已覆盖"
            print(f"{item.name} [{item.id}] {detail}".rstrip())
    elif args.character_command == "show":
        character = service.get(args.id)
        if character is None:
            raise ValueError("角色不存在")
        print(f"名称：{character.name}")
        print(f"ID：{character.id}")
        for label, value in (
            ("描述", character.description),
            ("性格", character.personality),
            ("背景", character.background),
            ("说话风格", character.speaking_style),
        ):
            if value:
                print(f"{label}：{value}")
        if character.has_system_prompt:
            print(f"系统提示词：{character.system_prompt}")
    elif args.character_command == "add":
        if args.system_prompt and any(
            (args.description, args.personality, args.background, args.speaking_style)
        ):
            print("提示：已设置 --system-prompt，其余字段不会生效", file=sys.stderr)
        created = service.create(
            name=args.name,
            description=args.description,
            personality=args.personality,
            background=args.background,
            speaking_style=args.speaking_style,
            system_prompt=args.system_prompt,
        )
        print(f"已创建 {created.name} ({created.id})")
    elif args.character_command == "delete":
        service.delete(args.id)
        print(f"已删除 {args.id}")


def _print_memories(items) -> None:
    if not items:
        print("尚无记忆")
        return
    for item in items:
        print(f"[{item.id}] {item.tier}/{item.type}/{item.status} {item.content}")


def _memory(args) -> None:
    service = MemoryService()
    if args.memory_command == "list":
        _print_memories(
            service.list(include_inactive=args.include_inactive, tier=args.tier)
        )
    elif args.memory_command == "search":
        _print_memories(
            service.search(
                args.query, include_inactive=args.include_inactive, tier=args.tier
            )
        )
    elif args.memory_command == "show":
        item = service.get(args.id)
        if item is None:
            raise ValueError("记忆不存在")
        print(f"ID：{item.id}")
        print(f"类型：{item.type}")
        print(f"层级：{item.tier}")
        print(f"状态：{item.status}")
        print(f"来源：{item.origin}")
        print(f"内容：{item.content}")
        if item.supersedes_id:
            print(f"替换：{item.supersedes_id}")
        if item.source_message_id:
            print(f"来源消息：{item.source_message_id}")
            if item.source_content is None:
                print("来源内容：已删除")
            else:
                print(f"来源内容：{item.source_content}")
                print(f"来源会话：{item.source_conversation_id}")
    elif args.memory_command == "recall-explain":
        print(json.dumps(service.recall_explain(args.query), ensure_ascii=False, indent=2))
    elif args.memory_command == "add":
        item = service.add(type=args.type, content=args.content)
        print(f"已添加记忆 {item.id}")
    elif args.memory_command == "edit":
        item = service.edit(args.id, content=args.content)
        print(f"已纠正记忆，新 ID：{item.id}")
    elif args.memory_command == "complete":
        service.complete(args.id)
        print(f"已完成 {args.id}")
    elif args.memory_command == "forget":
        if not args.apply:
            plan = service.plan_forget(
                memory_id=args.id, conversation_id=args.conversation_id
            )
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            print("未修改数据；确认后加 --apply 执行")
        elif args.conversation_id:
            count = service.forget_conversation(args.conversation_id)
            print(f"已遗忘会话 {args.conversation_id}，删除情景观察 {count} 条")
        elif args.id:
            service.forget(args.id)
            print(f"已删除记忆 {args.id}；历史聊天未删除")
        else:
            raise ValueError("需要指定记忆 ID 或 --conversation")
    elif args.memory_command == "index":
        from zhiyu.core.memory.indexer import rebuild_index
        from zhiyu.core.memory.store import MemoryStore

        store = MemoryStore()
        with SessionLocal() as db:
            stats = rebuild_index(db, store)
        print(" ".join(f"{key}={value}" for key, value in sorted(stats.items())))
    elif args.memory_command == "export":
        from zhiyu.core.memory.store import MemoryStore

        store = MemoryStore()
        with SessionLocal() as db:
            identity_id = IdentityRepository().local(db).id
        for path in store.list_memory_files(identity_id):
            if path.exists():
                print(f"# {path.name}")
                print(path.read_text(encoding="utf-8"))
    elif args.memory_command == "consolidate":
        result = asyncio.run(
            ConsolidationProcessor().run_sweep(dry_run=not args.apply, force=args.force)
        )
        print(json.dumps(result, ensure_ascii=False))
    elif args.memory_command == "consolidation":
        if args.consolidation_command == "list":
            runs = ConsolidationProcessor().list_runs()
            if not runs:
                print("尚无巩固记录")
            for run in runs:
                print(f"[{run.created_at:%Y-%m-%d %H:%M}] {run.status} {run.summary}")
    elif args.memory_command == "status":
        status = service.status()
        print(" ".join(f"{key}={value}" for key, value in sorted(status.items())))
    elif args.memory_command == "sync":
        result = asyncio.run(MemoryJobProcessor().process_pending(recover=True))
        print(" ".join(f"{status}={count}" for status, count in sorted(result.items())))
    elif args.memory_command == "retry":
        processor = MemoryJobProcessor()
        reset = processor.retry_failed()
        result = asyncio.run(processor.process_pending(recover=True))
        print(
            f"reset={reset} "
            + " ".join(f"{status}={count}" for status, count in sorted(result.items()))
        )


def _qq(args) -> None:
    service = ChannelService()
    if args.qq_command == "configure":
        token = None
        if not args.token_env and not args.no_token and sys.stdin.isatty():
            token = getpass("Access Token（留空表示不使用）: ").strip() or None
        service.configure_qq(
            args.endpoint,
            token=token,
            token_env=args.token_env,
            clear_token=args.no_token,
            owner_user_id=args.owner_user_id,
            clear_owner_user_id=args.clear_owner_user_id,
            allow_group_messages=args.group_messages,
            group_require_mention=args.group_require_mention,
        )
        print(f"QQ 已配置：{args.endpoint}")
    elif args.qq_command == "status":
        config = service.configured_qq()
        if config is None:
            print("QQ 尚未配置")
        else:
            token = (
                "已配置"
                if config["token_readable"]
                else "引用存在但不可读取"
                if config["has_token"]
                else "未配置"
            )
            print(
                f"endpoint={config['endpoint']} token={token} "
                f"owner_user_id={config['owner_user_id']} "
                f"groups={config['allow_group_messages']} "
                f"group_require_mention={config['group_require_mention']}"
            )
            try:
                import httpx

                response = httpx.get(
                    os.getenv("ZHIYU_WEB_URL", "http://127.0.0.1:8765")
                    + "/api/channels",
                    timeout=1.0,
                    trust_env=False,
                )
                response.raise_for_status()
                runtime_state = next(
                    (item for item in response.json() if item.get("channel") == "qq"),
                    None,
                )
            except Exception:
                runtime_state = None
            if runtime_state:
                print(
                    f"runtime={runtime_state.get('status')} "
                    f"connected={runtime_state.get('connected')} "
                    f"last_error={runtime_state.get('last_error')}"
                )
            else:
                print("runtime=unavailable（zhiyu serve 未运行或端口不同）")
    elif args.qq_command == "listen":
        try:
            asyncio.run(_qq_listen(service))
        except KeyboardInterrupt:
            print("\nQQ 监听已停止")
    elif args.qq_command == "events":
        for item in service.list_events(args.limit):
            error = f" error={item['last_error']}" if item["last_error"] else ""
            print(f"{item['id']} status={item['status']} attempts={item['attempts']}{error}")
    elif args.qq_command == "replay":
        service.replay_event(args.event_id)
        print(f"事件已重新排队：{args.event_id}")
    elif args.qq_command == "deliveries":
        for item in service.list_deliveries(args.limit):
            retry = f" retry_of={item['retry_of_id']}" if item["retry_of_id"] else ""
            error = f" error={item['last_error']}" if item["last_error"] else ""
            print(f"{item['id']} status={item['status']}{retry}{error}")
    elif args.qq_command == "retry-delivery":
        queued = service.retry_delivery(
            args.delivery_id, allow_unknown=args.confirm_unknown
        )
        print(f"投递已重新排队：{queued}")
    elif args.qq_command == "groups":
        if args.qq_groups_command == "list":
            for item in service.list_group_policies():
                tools = ",".join(item["tool_allowlist"]) or "none"
                print(
                    f"{item['group_id']} enabled={item['enabled']} "
                    f"require_mention={item['require_mention']} tools={tools}"
                )
        elif args.qq_groups_command == "allow":
            service.set_group_policy(
                args.group_id,
                enabled=True,
                require_mention=args.require_mention,
                tool_allowlist=args.allow_tool,
                system_prompt=args.system_prompt,
            )
            print(f"群 {args.group_id} 已允许")
        elif args.qq_groups_command == "deny":
            service.set_group_policy(args.group_id, enabled=False)
            print(f"群 {args.group_id} 已禁用")
    elif args.qq_command == "doctor":
        _qq_doctor(service)


def _qq_doctor(service: ChannelService) -> None:
    config = service.configured_qq()
    if config is None:
        raise ValueError("QQ 尚未配置")
    print(f"✓ 配置：{config['endpoint']}")
    print(
        f"{'✓' if config['token_readable'] else '!'} Access Token："
        f"{'可读取' if config['token_readable'] else '不可读取或未配置'}"
    )
    endpoint = urlsplit(config["endpoint"])
    if endpoint.hostname and endpoint.port:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            listening = probe.connect_ex((endpoint.hostname, endpoint.port)) == 0
        print(f"{'✓' if listening else '!'} WebSocket 监听：{'已启动' if listening else '尚未启动'}")
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", "zhiyu-napcat"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("! Docker：无法读取状态")
    else:
        status = result.stdout.strip() if result.returncode == 0 else "未找到 zhiyu-napcat"
        print(f"{'✓' if status == 'running' else '!'} Docker：{status}")


def _embedding(args) -> None:
    from zhiyu.core.providers.embedding import load_config, resolve_api_key, save_config
    from zhiyu.infrastructure.config.keystore import keystore

    if args.embedding_command == "status":
        with SessionLocal() as db:
            config = load_config(db)
        if config is None:
            print("embedding 未配置")
        else:
            key = "已配置" if resolve_api_key(config.api_key_ref) else "未配置（key 无效）"
            print(f"base_url={config.base_url} model={config.model} api_key={key}")
    elif args.embedding_command == "configure":
        if args.api_key_env:
            api_key_ref = f"env:{args.api_key_env}"
        else:
            if not sys.stdin.isatty():
                raise ValueError("非交互环境请使用 --api-key-env")
            api_key = getpass("API Key: ").strip()
            if not api_key:
                raise ValueError("API Key 不能为空")
            keystore.set("embedding", api_key)
            api_key_ref = "embedding"
        with SessionLocal() as db:
            save_config(
                db,
                base_url=args.base_url.rstrip("/"),
                model=args.model,
                api_key_ref=api_key_ref,
            )
        print("embedding 已配置")


def _mcp(args) -> None:
    service = McpService()
    if args.mcp_command == "list":
        items = service.list()
        if not items:
            print("尚未配置 MCP服务器")
            return
        for item in items:
            tools = "legacy-all (请检查权限)" if item.legacy_all_tools else ",".join(item.tool_allowlist) or "none"
            print(
                f"{item.name}\t{'enabled' if item.enabled else 'disabled'}\t"
                f"{item.transport}\t{item.command or item.url}\t{item.status}\ttools={tools}"
            )
    elif args.mcp_command == "doctor":
        failures = 0
        for item in service.list():
            if not item.enabled:
                continue
            try:
                result = asyncio.run(service.test(item.name))
                print(f"✓ {item.name}: {len(result['tools'])} tools, {len(result['resources'])} resources, {len(result['prompts'])} prompts")
            except ValueError as exc:
                failures += 1
                print(f"✗ {item.name}: {exc}")
        if not failures:
            print("已启用的 MCP Server 均可连接")
    elif args.mcp_command == "add":
        transports = {"stdio": "stdio", "http": "streamable_http", "streamable_http": "streamable_http", "sse": "sse"}
        if args.first in transports:
            if not args.second:
                raise ValueError("请提供 MCP 名称")
            name, transport = args.second, transports[args.first]
            command = args.command
        else:
            name, command, transport = args.first, args.command or args.second, args.transport or "stdio"
            transport = transports.get(transport, transport)
        item = service.configure(
            name,
            command,
            args.arg,
            args.allow_tool or None,
            transport=transport,
            url=args.url,
            enabled=False,
        )
        print(f"MCP 已保存：{item.name}（{item.transport}，默认未启用、无工具授权）")
    elif args.mcp_command == "disable":
        service.disable(args.name)
        print(f"MCP 已禁用：{args.name}")
    elif args.mcp_command == "enable":
        config = service.get(args.name)
        if config["transport"] == "stdio":
            summary = f"{config['command']} {' '.join(config['args'])}".strip()
            if sys.stdin.isatty():
                confirmation = input(f"将以当前用户权限启动：{summary}\n确认启用？[y/N] ")
                if confirmation.strip().lower() not in {"y", "yes"}:
                    raise ValueError("已取消启用")
            elif not args.confirm_command:
                raise ValueError("启用 stdio MCP 会执行配置命令；非交互环境请使用 --confirm-command")
        service.enable(args.name)
        print(f"MCP 已启用：{args.name}；运行中的知语将在数秒内连接")
    elif args.mcp_command == "remove":
        if not args.confirm:
            raise ValueError("删除配置会移除该 Server 的 Keychain 凭据；请追加 --confirm")
        service.remove(args.name)
        print(f"已删除 MCP 配置：{args.name}（不会卸载外部 Server 程序）")
    elif args.mcp_command == "show":
        value = service.get(args.name)
        value.pop("secret_refs", None)
        value["env"] = {key: "已设置" for key in value.get("env", {})}
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif args.mcp_command in {"test", "tools", "resources", "prompts"}:
        result = asyncio.run(service.test(args.name))
        if args.mcp_command == "test":
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.mcp_command == "tools":
            current = service.get(args.name)
            if args.deny_all and (args.allow_all or args.allow):
                raise ValueError("--deny-all 不能与 --allow 或 --allow-all 同时使用")
            if args.allow_all:
                service.set_tool_allowlist(args.name, [], allow_all=True)
            elif args.allow:
                known = {item.removeprefix(f"{args.name}.") for item in result["tools"]}
                unknown = set(args.allow) - known
                if unknown:
                    raise ValueError(f"Server 未提供这些工具：{', '.join(sorted(unknown))}")
                service.set_tool_allowlist(args.name, args.allow)
            elif args.deny_all:
                service.set_tool_allowlist(args.name, [], allow_all=False)
            if args.allow_all:
                current["legacy_all_tools"] = True
            elif args.allow or args.deny_all:
                current["tool_allowlist"] = args.allow
                current["legacy_all_tools"] = False
            for name in result["tools"]:
                raw = name.removeprefix(f"{args.name}.")
                allowed = current["legacy_all_tools"] or raw in current["tool_allowlist"]
                print(f"{'[x]' if allowed else '[ ]'} {raw}")
            if args.allow or args.allow_all or args.deny_all:
                print("工具权限已更新；新连接会应用此白名单")
        elif args.mcp_command == "resources":
            if args.deny_all and args.allow:
                raise ValueError("--deny-all 不能与 --allow 同时使用")
            if args.allow or args.deny_all:
                selected = args.allow if args.allow else []
                known = {item["uri"] for item in result["resources"]}
                unknown = set(selected) - known
                if unknown:
                    raise ValueError(f"Server 未提供这些 Resource URI：{', '.join(sorted(unknown))}")
                service.set_capability_allowlist(args.name, "resource", selected)
            print(json.dumps(result["resources"], ensure_ascii=False, indent=2))
        else:
            if args.deny_all and args.allow:
                raise ValueError("--deny-all 不能与 --allow 同时使用")
            if args.allow or args.deny_all:
                selected = args.allow if args.allow else []
                known = {item["name"] for item in result["prompts"]}
                unknown = set(selected) - known
                if unknown:
                    raise ValueError(f"Server 未提供这些 Prompt：{', '.join(sorted(unknown))}")
                service.set_capability_allowlist(args.name, "prompt", selected)
            print(json.dumps(result["prompts"], ensure_ascii=False, indent=2))
    elif args.mcp_command == "resource":
        if args.mcp_resource_command == "read":
            print(asyncio.run(service.read_resource(args.name, args.uri)))
    elif args.mcp_command == "prompt":
        arguments = {}
        for item in args.arg:
            key, sep, value = item.partition("=")
            if not sep or not key:
                raise ValueError("Prompt 参数格式必须是 key=value")
            arguments[key] = value
        print(asyncio.run(service.render_prompt(args.name, args.prompt, arguments)))
    elif args.mcp_command == "env":
        if args.mcp_env_command == "secret":
            if not sys.stdin.isatty():
                raise ValueError("非交互环境不接受命令行明文 Secret")
            value = getpass(f"{args.key}: ")
            service.set_env(args.name, args.key, value, secret=True)
        elif args.mcp_env_command == "set":
            service.set_env(args.name, args.key, args.value)
        else:
            service.set_env(args.name, args.key, None)
        print("MCP 环境配置已更新")
    elif args.mcp_command == "auth":
        if args.mcp_auth_command == "set":
            if not sys.stdin.isatty():
                raise ValueError("非交互环境不接受命令行明文凭据")
            value = getpass("Bearer Token / Header 值: ")
            if args.header.lower() == "authorization" and not value.lower().startswith("bearer "):
                value = "Bearer " + value
            service.set_header_secret(args.name, args.header, value)
        else:
            service.set_header_secret(args.name, args.header, None)
        print("MCP 凭据已更新")
    elif args.mcp_command == "reconnect":
        service.request_reconnect(args.name)
        print(f"已请求重新连接：{args.name}")
    elif args.mcp_command == "logs":
        item = next((server for server in service.list() if server.name == args.name), None)
        if item is None:
            raise ValueError("MCP Server 不存在")
        print(json.dumps({"status": item.status, "last_error": item.last_error, "retry_count": item.retry_count, "next_retry_at": item.next_retry_at}, ensure_ascii=False, indent=2))


def _skills(args) -> None:
    service = SkillService()
    command = args.skills_command
    if command != "validate":
        service.register_existing()
    if command == "list":
        print(json.dumps(service.list(), ensure_ascii=False, indent=2))
    elif command == "show":
        print(json.dumps(service.show(args.target), ensure_ascii=False, indent=2))
    elif command == "validate":
        print(json.dumps(service.validate(args.target), ensure_ascii=False, indent=2))
    elif command == "install":
        preview = service.preview(args.target, ref=args.ref, subdir=args.subdir)
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        if sys.stdin.isatty():
            confirmation = input("请确认以上来源、权限声明和文件清单，安装？[y/N] ")
            if confirmation.strip().lower() not in {"y", "yes"}:
                raise ValueError("已取消安装")
        elif not args.yes:
            raise ValueError("非交互安装请检查预览后追加 --yes")
        result = service.install(args.target, ref=preview["resolved_revision"], subdir=args.subdir)
        print(f"Skill 已安装：{result['name']}（{result['content_hash']}）")
    elif command in {"update", "diff"}:
        result = service.update(args.target, ref=getattr(args, "ref", None), apply=command == "update" and args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if command == "update" and not args.apply:
            print("以上为更新预览；检查后加 --apply 执行升级。")
    elif command in {"enable", "disable"}:
        service.enable(args.target, command == "enable")
        print(f"Skill {args.target} 已{'启用' if command == 'enable' else '禁用'}")
    elif command == "remove":
        if not args.confirm:
            raise ValueError("移除会把 Skill 放入 30 天回收站，请追加 --confirm")
        print(f"Skill 已移入回收站：{service.remove(args.target)}")
    elif command == "restore":
        print(f"Skill 已恢复：{service.restore(args.target)}")
    elif command == "reload":
        service.request_reload()
        print("已请求刷新 Skills；运行中的知语会在数秒内重载。")


async def _dream(args) -> None:
    processor = ConsolidationProcessor()
    if args.once:
        result = await processor.run_sweep(dry_run=False, force=True)
        print(json.dumps(result, ensure_ascii=False))
        return
    print(f"记忆巩固守护启动，间隔 {args.interval} 秒。按 Ctrl+C 停止。")
    await processor.run_forever(args.interval)


def _serve(args) -> None:
    try:
        is_loopback = args.host.lower() == "localhost" or ipaddress.ip_address(
            args.host
        ).is_loopback
    except ValueError as exc:
        raise ValueError("Web监听地址必须是本机回环地址") from exc
    if not is_loopback:
        raise ValueError("当前 WebUI 仅允许监听本机回环地址")
    if not 1 <= args.port <= 65535:
        raise ValueError("端口必须在 1 到 65535 之间")

    import uvicorn

    from zhiyu.api import create_app

    print(f"知语 WebUI：http://{args.host}:{args.port}")
    uvicorn.run(create_app(), host=args.host, port=args.port)


def run(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = _parser()
    args = parser.parse_args(_normalize_cli_args(argv if argv is not None else sys.argv[1:]))
    configure_logging()
    try:
        if args.command == "db" and args.db_command == "upgrade":
            upgrade_database()
            print("数据库已升级")
            return 0

        upgrade_database()
        if args.command == "doctor":
            checks = run_checks()
            icons = {"ok": "✓", "warn": "!", "fail": "✗"}
            for check in checks:
                print(f"{icons[check.status]} {check.name}: {check.detail}")
            return 1 if any(check.status == "fail" for check in checks) else 0
        if args.command == "serve":
            _serve(args)
        elif args.command == "chat":
            if not args.message and sys.stdin.isatty() and sys.stdout.isatty():
                _chat_tui(args)
            else:
                asyncio.run(_chat_line(args))
        elif args.command == "character":
            _character(args)
        elif args.command == "memory":
            _memory(args)
        elif args.command == "provider":
            _provider(args)
        elif args.command == "qq":
            _qq(args)
        elif args.command == "mcp":
            _mcp(args)
        elif args.command == "skills":
            _skills(args)
        elif args.command == "dream":
            try:
                asyncio.run(_dream(args))
            except KeyboardInterrupt:
                print("\n巩固守护已停止")
        elif args.command == "embedding":
            _embedding(args)
        return 0
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.debug:
            raise
        print(f"运行失败：{exc}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())
