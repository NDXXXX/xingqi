"""Character CLI commands."""

import sys

from zhiyu.application.characters import CharacterService

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
