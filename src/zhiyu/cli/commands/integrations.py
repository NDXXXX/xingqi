"""MCP, Skills and embedding CLI commands."""

import asyncio
import getpass
import json
import sys

from zhiyu.application.mcp import McpService
from zhiyu.application.providers import ProviderService
from zhiyu.application.skills import SkillService

def _embedding(args) -> None:
    service = ProviderService()
    if args.embedding_command == "status":
        status = service.embedding_status()
        if status is None:
            print("embedding 未配置")
        else:
            key = "已配置" if status["api_key_set"] else "未配置（key 无效）"
            print(f"base_url={status['base_url']} model={status['model']} api_key={key}")
    elif args.embedding_command == "configure":
        api_key = None
        if not args.api_key_env:
            if not sys.stdin.isatty():
                raise ValueError("非交互环境请使用 --api-key-env")
            api_key = getpass("API Key: ").strip()
            if not api_key:
                raise ValueError("API Key 不能为空")
        service.configure_embedding(
            base_url=args.base_url, model=args.model,
            api_key=api_key, api_key_env=args.api_key_env,
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
