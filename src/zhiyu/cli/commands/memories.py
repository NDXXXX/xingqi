"""Memory and consolidation CLI commands."""

import asyncio
import json

from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.application.memories import MemoryService
from zhiyu.application.memory_jobs import MemoryJobProcessor
from zhiyu.infrastructure.database.db import SessionLocal
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository

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

async def _dream(args) -> None:
    processor = ConsolidationProcessor()
    if args.once:
        result = await processor.run_sweep(dry_run=False, force=True)
        print(json.dumps(result, ensure_ascii=False))
        return
    print(f"记忆巩固守护启动，间隔 {args.interval} 秒。按 Ctrl+C 停止。")
    await processor.run_forever(args.interval)
