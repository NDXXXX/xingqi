"""Agent workspaces isolate history, memory and integration permissions."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.characters import CharacterService
from zhiyu.application.consolidation_jobs import ConsolidationProcessor
from zhiyu.application.mcp import McpService
from zhiyu.application.memories import MemoryService
from zhiyu.application.memory_jobs import MemoryJobProcessor
from zhiyu.application.skills import SkillService
from zhiyu.core.agent.context import build_tool_registry, with_agent_context
from zhiyu.core.memory.deep_recall import deep_recall
from zhiyu.core.memory.indexer import rebuild_index
from zhiyu.core.memory.manager import MemoryManager
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.models import Character, Conversation, Identity
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository
from zhiyu.infrastructure.database.repositories.identity_repository import IdentityRepository
from zhiyu.infrastructure.database.repositories.memory_job_repository import MemoryJobRepository
from zhiyu.infrastructure.database.repositories.memory_repository import MemoryRepository
from zhiyu.infrastructure.database.repositories.message_repository import MessageRepository
from zhiyu.infrastructure.database.repositories.provider_repository import ProviderRepository
from zhiyu.integrations.mcp.manager import McpManager
from zhiyu.integrations.skills.registry import SkillRegistry


@pytest.fixture
def workspace(tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    chars = CharacterService(factory)
    a, b = chars.create(name="山雀", personality="喜欢讲故事"), chars.create(name="银杏", personality="简洁严谨")
    store = MemoryStore(tmp_path / "memory")
    return factory, store, a.id, b.id


def conversation(factory, character_id=None):
    with factory() as db:
        identity = IdentityRepository().for_agent(db, character_id)
        return ConversationRepository().create(db, title="对话", channel="local", identity_id=identity.id, character_id=character_id).id


def test_blank_workspaces_and_memory_lifecycle(workspace):
    factory, store, a, b = workspace
    services = [MemoryService(factory, store, scope) for scope in (None, a, b)]
    assert all(service.list() == [] for service in services)
    default, first, second = [service.add(type="preference", content=f"用户喜欢{fruit}") for service, fruit in zip(services, ("苹果", "柚子", "樱桃"))]
    assert [len(service.list()) for service in services] == [1, 1, 1]
    assert services[1].get(second.id) is None
    assert services[0].get(first.id) is None
    for action in (services[2].edit, services[2].confirm, services[2].keep, services[2].forget):
        with pytest.raises(ValueError):
            action(first.id, **({"content": "越权修改"} if action == services[2].edit else {}))
    with factory() as db:
        row = MemoryRepository().get(db, first.id)
        assert row.identity_id == a and row.character_id == a
        assert a in row.file_path and b not in row.file_path
        # Old global sharing cannot make a default record visible to an Agent.
        MemoryRepository().get(db, default.id).shared = True
        db.commit()
        assert {row.id for row in MemoryRepository().list_visible(db, b)} == {second.id}
        for scope in (a, b):
            rebuild_index(db, store, scope)
    services[1].edit(first.id, content="用户喜欢柚子茶")
    assert services[2].list()[0].content == "用户喜欢樱桃"
    assert services[1].clear() >= 1
    assert services[1].list() == []
    services[1].rebuild_index()
    assert services[1].list() == []
    assert services[2].get(second.id) is not None


def test_persona_bootstrap_and_history_are_scoped(workspace):
    factory, store, a, b = workspace
    default_id = conversation(factory)
    first_id, second_id = conversation(factory, a), conversation(factory, b)
    with factory() as db:
        local = IdentityRepository().local(db).id
        store.write_bootstrap_file(local, "AGENTS.md", "全局操作规则")
        store.write_bootstrap_file(local, "SOUL.md", "仅默认助手人格")
        store.write_bootstrap_file(local, "BOOTSTRAP.md", "仅默认初次引导")
        store.append(store.identity_path_for(local), "助手名字是测试旧名字", meta={"type": "profile"})
        MessageRepository().create(db, conversation_id=first_id, role="user", content="我的猫叫糯米")
        MessageRepository().create(db, conversation_id=default_id, role="user", content="我的猫叫奶糖")
        assert "糯米" in deep_recall(db, a, "我的猫叫什么")
        assert deep_recall(db, b, "我的猫叫什么") is None
        result = with_agent_context(db, db.get(Conversation, second_id), "你好", [{"role": "user", "content": "你好"}], memory_store=store)
        system = result[0]["content"]
        assert "银杏" in system and "简洁严谨" in system and "全局操作规则" in system
        assert all(text not in system for text in ("仅默认助手人格", "仅默认初次引导", "测试旧名字", "山雀"))
    MemoryService(factory, store, a).clear()
    with factory() as db:
        assert deep_recall(db, a, "我的猫叫什么") is None
        assert db.get(Conversation, first_id) is not None
        MessageRepository().create(db, conversation_id=first_id, role="user", content="我的猫现在叫小白")
        assert "小白" in deep_recall(db, a, "我的猫叫什么")
        assert "糯米" not in deep_recall(db, a, "我的猫叫什么")


def test_existing_session_cannot_change_agent_and_delete_is_protected(workspace):
    factory, store, a, b = workspace
    first_id = conversation(factory, a)
    with factory() as db:
        MessageRepository().create(db, conversation_id=first_id, role="user", content="你好")
    chars = CharacterService(factory)
    with pytest.raises(ValueError, match="不能更换智能体"):
        chars.assign_to_conversation(first_id, b)
    with pytest.raises(ValueError, match="先删除"):
        chars.delete(a)
    MemoryService(factory, store, b).add(type="fact", content="独立记忆")
    with pytest.raises(ValueError, match="先删除"):
        chars.delete(b)
    chars.update(a, name="改名后的山雀")
    with factory() as db:
        assert db.get(Conversation, first_id).character_id == a
        assert db.get(Identity, a).display_name == "改名后的山雀"
        assert db.get(Character, b).name == "银杏"


def test_same_mcp_name_has_separate_configs_and_connections(workspace):
    factory, _store, a, b = workspace
    default, first, second = [McpService(factory, character_id=scope) for scope in (None, a, b)]
    first.configure("lookup", "a-command", [], enabled=True)
    second.configure("lookup", "b-command", [], enabled=True)
    default.configure("lookup", "default-command", [])
    assert first.get("lookup")["command"] == "a-command"
    assert second.get("lookup")["command"] == "b-command"
    assert all(not service.get("lookup")["tool_allowlist"] for service in (default, first, second))
    first.set_tool_allowlist("lookup", ["search"])
    assert second.get("lookup")["tool_allowlist"] == []
    configs = default.runtime_configs(all_agents=True)
    assert {config["character_id"] for config in configs} == {a, b}
    manager = McpManager()
    for config in configs:
        manager._configs[config["id"]] = config
        manager._connections[config["id"]] = SimpleNamespace(name="lookup", tools=[SimpleNamespace(name="lookup.search")])
    assert [tool.name for tool in manager.tools(a)] == ["lookup.search"]
    assert manager.tools(b) == []
    assert manager.tools() == []
    assert manager.connection("lookup", a) is not manager.connection("lookup", b)
    assert manager.connection("lookup") is None
    first.remove("lookup")
    assert second.get("lookup")["command"] == "b-command"


async def test_skill_link_and_read_permissions_are_independent(workspace, tmp_path, monkeypatch):
    factory, store, a, b = workspace
    source = tmp_path / "research"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: research\ndescription: 分析仓库\n---\n\n独立技能正文")
    packages = tmp_path / "skills"
    first, second = SkillService(factory, packages, a), SkillService(factory, packages, b)
    first.install(source)
    assert first.show("research")["enabled"]
    assert not second.show("research")["enabled"]
    assert not SkillService(factory, packages).show("research")["enabled"]
    registry = SkillRegistry(packages)
    registry.reload(SkillService(factory, packages).enabled_overrides())
    import zhiyu.core.agent.context as context
    monkeypatch.setattr(context, "skill_registry", registry)
    tools = build_tool_registry(McpManager(), session_factory=factory, identity_id=a, character_id=a, memory_store=store)
    assert await tools.get("read_skill").execute("research") == "独立技能正文"
    assert "read_skill" not in build_tool_registry(McpManager(), session_factory=factory, identity_id=b, character_id=b, memory_store=store).names()
    second.enable("research", True)
    first.enable("research", False)
    assert not first.show("research")["enabled"] and second.show("research")["enabled"]
    first.remove("research")
    assert (packages / "research" / "SKILL.md").exists()
    assert second.show("research")["enabled"]
    with pytest.raises(ValueError, match="仍关联"):
        SkillService(factory, packages).remove("research")


class ObservationProvider(AIProvider):
    async def chat(self, messages, **kwargs):
        return LLMResponse(content=json.dumps([{"type": "preference", "content": "用户喜欢柚子", "evidence": "喜欢柚子"}], ensure_ascii=False))


async def test_extraction_tools_and_consolidation_keep_agent_scope(workspace):
    factory, store, a, b = workspace
    first_id = conversation(factory, a)
    manager = MemoryManager(store)
    with factory() as db:
        message = MessageRepository().create(db, conversation_id=first_id, role="user", content="记住我喜欢柚子")
        saved = await manager.extract_and_save(db, ObservationProvider(None), "fake", message.content, "", a, user_message_id=message.id)
        assert saved and all(row.character_id == a for row in saved)
        db.commit()
    assert MemoryService(factory, store, b).list() == []
    tools_a = build_tool_registry(McpManager(), session_factory=factory, identity_id=a, character_id=a, memory_store=store)
    tools_b = build_tool_registry(McpManager(), session_factory=factory, identity_id=b, character_id=b, memory_store=store)
    found = await tools_a.get("memory_search").execute("柚子")
    assert found["results"]
    memory_id = found["results"][0]["id"]
    assert (await tools_a.get("memory_get").execute(memory_id))["found"]
    assert not (await tools_b.get("memory_get").execute(memory_id))["found"]
    assert not (await tools_b.get("memory_search").execute("柚子"))["results"]
    processor = ConsolidationProcessor(factory, store)
    with factory() as db:
        assert processor._pending(db, b) == []
        assert all(row.character_id == a for row in processor._pending(db, a))


async def test_job_snapshot_rejects_mismatched_workspace(workspace):
    factory, store, a, b = workspace
    conv_id = conversation(factory, a)
    with factory() as db:
        provider = ProviderRepository().create(db, name="fake", provider_type="openai", api_key_ref="env:FAKE_KEY")
        message = MessageRepository().create(db, conversation_id=conv_id, role="user", content="喜欢柚子")
        job = MemoryJobRepository().create(db, user_message_id=message.id, assistant_message_id=None, identity_id=b, character_id=b, provider_id=provider.id, model="fake")
        db.commit()
        job_id = job.id
    processor = MemoryJobProcessor(factory, memory_manager=MemoryManager(store))
    assert await processor._process_one(job_id) == "cancelled"
    assert MemoryService(factory, store, a).list() == MemoryService(factory, store, b).list() == []


def test_web_create_select_and_scoped_management(tmp_path):
    from test_web_api import make_client
    client, factory, store, provider_id, model_name = make_client(tmp_path)
    with client:
        first = client.post("/api/agents", json={"name": "自由名称", "personality": "讲故事"})
        assert first.status_code == 201
        a = first.json()["id"]
        b = client.post("/api/agents", json={"name": "另一个名字"}).json()["id"]
        assert client.get(f"/api/memories?character_id={a}").json() == []
        assert client.get(f"/api/mcp/servers?character_id={b}").json() == []
        memory = MemoryService(factory, store, a).add(type="fact", content="独立资料")
        assert client.get(f"/api/memories?character_id={a}").json()[0]["id"] == memory.id
        assert client.get(f"/api/memories?character_id={b}").json() == []
        assert client.delete(f"/api/memories/{memory.id}?character_id={b}").status_code == 404
        stream = client.post("/api/chat", json={"message": "你好", "character_id": a, "provider_id": provider_id, "model": model_name})
        events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
        conv_id = next(item["conversation_id"] for item in events if item["type"] == "done")
        assert client.get(f"/api/conversations?character_id={a}").json()[0]["id"] == conv_id
        assert client.get(f"/api/conversations?character_id={b}").json() == []
        wrong = client.post("/api/chat", json={"message": "不能改挂", "conversation_id": conv_id, "character_id": b})
        assert "属于其他智能体" in wrong.text
        assert client.get("/api/memories?character_id=missing").status_code == 404
        assert client.get("/api/mcp/servers?character_id=missing").status_code == 404
        assert client.get("/api/reminders/recent").status_code == 404
        assert client.post(f"/api/memories/clear?character_id={a}").status_code == 200
        assert client.get(f"/api/conversations/{conv_id}/messages").json()
