"""The ``zhiyu`` command-line entry point."""

import argparse
import asyncio
import ipaddress
import sys

from dotenv import load_dotenv

from zhiyu.application.doctor import run_checks
from zhiyu.cli.commands.chat import _chat_line, _chat_tui
from zhiyu.cli.commands.channels import _qq
from zhiyu.cli.commands.characters import _character
from zhiyu.cli.commands.integrations import _embedding, _mcp, _skills
from zhiyu.cli.commands.memories import _dream, _memory
from zhiyu.cli.commands.providers import handle_provider as _provider
from zhiyu.infrastructure.config.logging import configure_logging
from zhiyu.infrastructure.database.migrations import upgrade_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zhiyu", description="星栖 Personal AI Agent")
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

    print(f"星栖 WebUI：http://{args.host}:{args.port}")
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
