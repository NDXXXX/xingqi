import json
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.api import create_app
from zhiyu.application.chat import ChatService
from zhiyu.application.memories import MemoryService
from zhiyu.application.runtime import RuntimeHost
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
        skill_registry=Mock(reload=Mock()),
    )
    return (
        TestClient(create_app(host)),
        sessions,
        memory_manager.store,
        provider_id,
        model_name,
    )


def test_web_chat_stream_and_shared_conversation(tmp_path):
    client, _sessions, _store, provider_id, model_name = make_client(tmp_path)
    with client:
        assert client.get("/").status_code == 200
        assert "知语" in client.get("/").text
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
