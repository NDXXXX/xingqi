"""Provider CLI commands."""

import asyncio
from getpass import getpass
import sys

from zhiyu.application.providers import ProviderService


def handle_provider(args) -> None:
    service = ProviderService()
    if args.provider_command == "list":
        providers = service.list()
        if not providers:
            print("尚未配置 Provider")
        for item in providers:
            status = "enabled" if item.enabled else "disabled"
            print(f"{item.name} [{item.provider_type}] {status}: {', '.join(item.models)}")
    elif args.provider_command == "add":
        api_key = None
        if not args.api_key_env:
            if not sys.stdin.isatty():
                raise ValueError("非交互环境请使用 --api-key-env")
            api_key = getpass("API Key: ").strip()
            if not api_key:
                raise ValueError("API Key 不能为空")
        created = service.add(
            name=args.name,
            provider_type=args.provider_type,
            api_key=api_key,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
        )
        print(f"已添加 {created.name}: {', '.join(created.models)}")
    elif args.provider_command == "default":
        service.set_default(args.name, args.model)
        print(f"默认模型已设为 {args.name}/{args.model}")
    elif args.provider_command == "test":
        response = asyncio.run(service.test(args.name, args.model))
        print(response)
    elif args.provider_command == "fallback":
        service.set_fallbacks(args.name, args.fallbacks)
        value = " → ".join(args.fallbacks) if args.fallbacks else "无"
        print(f"{args.name} 的备用 Provider：{value}")
    elif args.provider_command == "vision":
        service.set_vision(args.name, args.model, args.enabled)
        print(f"{args.name}/{args.model} vision={args.enabled}")
