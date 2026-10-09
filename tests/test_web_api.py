import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.api import create_app
from zhiyu.application.chat import ChatService
from zhiyu.application.memories import MemoryService
from zhiyu.application.runtime import RuntimeHost
from zhiyu.application.skills import SkillService
from zhiyu.channels.manager import ChannelManager
from zhiyu.channels.router import ChannelRouter
from zhiyu.core.memory.store import MemoryStore
from zhiyu.core.providers.base import AIProvider, LLMResponse
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.provider_repository import (
    ProviderRepository,
)
from zhiyu.integrations.mcp.manager import McpManager


class FakeProvider(AIProvider):
    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content="来自 Web 的回复")

    async def stream_chat(self, messages, tools=None, **kwargs):
        yield "来自 Web"
        yield " 的回复"
        yield LLMResponse(content="来自 Web 的回复")


class FakeRouter:
    def get_provider(self, _config):
        return FakeProvider("fake-key")


class NoopMemoryManager:
    def __init__(self, store):
        self.store = store

    async def extract_and_save(self, *_args, **_kwargs):
        return []


def make_client(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        provider = ProviderRepository().create(
            db, name="Fake", provider_type="openai", api_key_ref="env:FAKE_KEY"
        )
        provider_id = provider.id
        model_name = provider.models[0].model_name
    memory_manager = NoopMemoryManager(MemoryStore(tmp_path / "memory"))
    chat = ChatService(sessions, FakeRouter(), memory_manager)
    channels = ChannelManager(ChannelRouter(chat), sessions)
    host = RuntimeHost(
        chat_service=chat,
        channel_manager=channels,
        mcp_manager=McpManager(),
        skill_service=SkillService(sessions, tmp_path / "skills"),
        skill_registry=Mock(reload=Mock()),
    )
    return (
        TestClient(
            create_app(host),
            base_url="http://127.0.0.1",
            headers={"X-Zhiyu-Request": "1"},
        ),
        sessions,
        memory_manager.store,
        provider_id,
        model_name,
    )


def test_web_chat_stream_and_shared_conversation(tmp_path):
    client, _sessions, _store, provider_id, model_name = make_client(tmp_path)
    with client:
        page = client.get("/")
        assert page.status_code == 200
        assert "星栖" in page.text
        assert 'id="root"' in page.text
        assert '/react/app.js' in page.text
        assert client.get("/react/app.js").status_code == 200
        assert client.get("/react/app.css").status_code == 200
        health = client.get("/api/health").json()
        assert health["started"] is True

        response = client.post(
            "/api/chat",
            json={
                "message": "你好",
                "provider_id": provider_id,
                "model": model_name,
            },
        )
        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        done = next(item for item in events if item["type"] == "done")
        assert "".join(
            item["text"] for item in events if item["type"] == "chunk"
        ) == "来自 Web 的回复"

        conversations = client.get("/api/conversations").json()
        assert conversations[0]["id"] == done["conversation_id"]
        messages = client.get(
            f"/api/conversations/{done['conversation_id']}/messages"
        ).json()
        assert [item["role"] for item in messages] == ["user", "assistant"]


def test_web_can_delete_conversation(tmp_path):
    client, _sessions, _store, provider_id, model_name = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/chat",
            json={
                "message": "待删除会话",
                "provider_id": provider_id,
                "model": model_name,
            },
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        conversation_id = next(
            item["conversation_id"] for item in events if item["type"] == "done"
        )

        deleted = client.delete(f"/api/conversations/{conversation_id}")

        assert deleted.status_code == 200
        assert deleted.json() == {"deleted": True}
        assert client.get("/api/conversations").json() == []
        assert client.get(
            f"/api/conversations/{conversation_id}/messages"
        ).status_code == 404
        assert client.delete(
            f"/api/conversations/{conversation_id}"
        ).status_code == 404


def test_web_memory_list_search_and_edit(tmp_path):
    client, sessions, store, _provider_id, _model_name = make_client(tmp_path)
    created = MemoryService(sessions, store=store).add(
        type="preference",
        content="用户喜欢爵士乐",
    )

    with client:
        listed = client.get("/api/memories").json()
        assert listed[0]["content"] == "用户喜欢爵士乐"
        searched = client.get("/api/memories", params={"query": "爵士"}).json()
        assert [item["id"] for item in searched] == [created.id]
        edited = client.patch(
            f"/api/memories/{created.id}",
            json={"content": "用户喜欢古典乐"},
        ).json()
        assert edited["content"] == "用户喜欢古典乐"


def test_chat_rejects_empty_message(tmp_path):
    client, *_ = make_client(tmp_path)
    with client:
        response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400


def test_web_management_can_configure_provider_mcp_and_qq(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path)
    monkeypatch.setenv("WEB_PROVIDER_KEY", "test-key")
    with client:
        provider = client.post(
            "/api/providers",
            json={"name": "WebProvider", "provider_type": "openai", "api_key_env": "WEB_PROVIDER_KEY"},
        )
        assert provider.status_code == 200
        assert provider.json()["name"] == "WebProvider"

        mcp = client.post(
            "/api/mcp/servers",
            json={"name": "web-mcp", "transport": "streamable_http", "url": "https://mcp.example.com/mcp"},
        )
        assert mcp.status_code == 200
        assert mcp.json()["name"] == "web-mcp"

        qq = client.put(
            "/api/qq/config",
            json={"endpoint": "ws://127.0.0.1:6199/ws", "owner_user_id": "12345"},
        )
        assert qq.status_code == 200
        assert qq.json()["owner_user_id"] == "12345"


def test_web_default_provider_endpoint_matches_chat_fallback(tmp_path):
    client, _sessions, _store, _provider_id, model_name = make_client(tmp_path)
    with client:
        selected = client.get("/api/providers/default")
    assert selected.status_code == 200
    assert selected.json() == {"provider": "Fake", "model": model_name}


def test_web_provider_model_and_fallback_management(tmp_path, monkeypatch):
    client, *_ = make_client(tmp_path)
    monkeypatch.setenv("WEB_PROVIDER_KEY", "not-returned")
    with client:
        created = client.post("/api/providers", json={
            "name": "Backup", "provider_type": "openai", "api_key_env": "WEB_PROVIDER_KEY"
        })
        assert created.status_code == 200
        detail = client.get("/api/providers/Backup").json()
        assert detail["api_key_env"] == "WEB_PROVIDER_KEY"
        assert "not-returned" not in json.dumps(detail)
        model = client.post("/api/providers/Backup/models", json={
            "model_name": "vision-model", "supports_vision": True, "context_window": 4096
        })
        assert model.status_code == 200
        assert model.json()["supports_vision"] is True
        updated = client.put(
            f"/api/providers/Backup/models/{model.json()['id']}",
            json={"max_output_tokens": 1024},
        )
        assert updated.json()["max_output_tokens"] == 1024
        assert client.put("/api/providers/Fake/fallbacks", json={"providers": ["Backup"]}).status_code == 200
        assert client.get("/api/providers/Fake").json()["fallbacks"] == ["Backup"]


def test_web_admin_rejects_cross_origin_write(tmp_path):
    client, *_ = make_client(tmp_path)
    with client:
        response = client.post(
            "/api/providers",
            headers={"Origin": "https://attacker.example"},
            json={"name": "Blocked", "provider_type": "openai", "api_key_env": "FAKE_KEY"},
        )
    assert response.status_code == 403


def test_web_boundary_covers_memory_chat_and_reads(tmp_path):
    client, *_ = make_client(tmp_path)
    with client:
        assert client.post(
            "/api/memories/missing/confirm",
            headers={"Origin": "https://attacker.example"},
        ).status_code == 403
        assert client.post(
            "/api/chat",
            headers={"Origin": "https://attacker.example"},
            json={"message": "hello"},
        ).status_code == 403
        assert client.post(
            "/api/runs/missing/cancel",
            headers={"Origin": "https://attacker.example"},
        ).status_code == 403
        assert client.get(
            "/api/memories", headers={"Host": "attacker.example"}
        ).status_code == 403
        assert client.get(
            "/api/conversations", headers={"Host": "attacker.example"}
        ).status_code == 403
        assert client.post(
            "/api/memories/missing/confirm",
            headers={"X-Zhiyu-Request": ""},
        ).status_code == 403
        assert client.post(
            "/api/memories/missing/confirm",
            headers={"Origin": "null"},
        ).status_code == 403
        assert client.post(
            "/api/memories/missing/confirm",
            headers={"Origin": "http://127.0.0.1:9999"},
        ).status_code == 403
        assert client.get("/").status_code == 200


async def test_web_boundary_rejects_non_loopback_peer(tmp_path):
    client, *_ = make_client(tmp_path)
    transport = ASGITransport(app=client.app, client=("192.0.2.1", 12345))
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as remote:
        response = await remote.get("/api/memories")
    assert response.status_code == 403




def test_integration_status_apis_do_not_expose_secret_values(tmp_path):
    client, *_ = make_client(tmp_path)
    host = client.app.state.runtime

    class MemorySecrets:
        def set(self, ref, value):
            self.value = value

        def get(self, _ref):
            return self.value

        def delete(self, _ref):
            self.value = None

    host.mcp_service.secrets = MemorySecrets()
    host.mcp_service.configure(
        "docs", None, [], transport="streamable_http", url="https://mcp.example.com/mcp"
    )
    host.mcp_service.set_header_secret("docs", "Authorization", "do-not-leak")

    with client:
        servers = client.get("/api/mcp/servers").json()
        detail = client.get("/api/mcp/servers/docs").json()
        skills = client.get("/api/skills").json()

    assert servers[0]["name"] == "docs"
    assert "do-not-leak" not in json.dumps(servers)
    assert "secret_refs" not in json.dumps(servers)
    assert "do-not-leak" not in json.dumps(detail)
    assert "secret_refs" not in json.dumps(detail)
    assert detail["secret_names"] == ["header:Authorization"]
    assert isinstance(skills, list)
