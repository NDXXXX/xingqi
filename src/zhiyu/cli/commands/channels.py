"""QQ and channel CLI commands."""

import asyncio
import getpass
import os
import socket
import subprocess
import sys
from urllib.parse import urlsplit

from zhiyu.application.channels import ChannelService

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
