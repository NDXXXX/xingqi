"""Chat SSE → Message → Agent Run 的完整 API 链路。"""

import json
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.api.agent_runs import router as agent_runs_router
from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.errors import install_error_handlers
from app.database import models  # noqa: F401
from app.database.db import Base, get_db
from app.database.repositories.provider_repository import ProviderRepository
from app.providers.base import AIProvider, LLMResponse


class FakeStreamingProvider(AIProvider):
    async def chat(self, messages, tools=None, stream=False, **kwargs):
        return LLMResponse(content="你好，测试完成")

    async def stream_chat(self, messages, tools=None, **kwargs):
        yield "你好，"
        yield "测试完成"
        yield LLMResponse(content="你好，测试完成")


def test_chat_stream_persists_messages_and_agent_run(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    provider = ProviderRepository().create(
        db,
        name="Fake",
        provider_type="openai",
        api_key_ref="fake-secret-ref",
        base_url="http://example.invalid",
    )
    model = provider.models[0]
    db.close()

    monkeypatch.setattr(chat_api, "SessionLocal", session_factory)
    monkeypatch.setattr(chat_api.provider_router, "get_provider", lambda _provider: FakeStreamingProvider(None))
    monkeypatch.setattr(chat_api.memory_manager, "extract_and_save", AsyncMock())

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(conversations_router)
    app.include_router(agent_runs_router)
    app.include_router(chat_router)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        conversation = client.post(
            "/api/conversations", json={"title": "Integration", "channel": "desktop"}
        ).json()
        response = client.post(
            "/api/chat/stream",
            json={
                "conversation_id": conversation["id"],
                "message": "你好",
                "provider_id": provider.id,
                "model": model.model_name,
            },
        )
        assert response.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert [event["text"] for event in events if event["type"] == "chunk"] == [
            "你好，",
            "测试完成",
        ]
        done = next(event for event in events if event["type"] == "done")
        messages = client.get(f"/api/conversations/{conversation['id']}/messages").json()
        runs = client.get(f"/api/agent/conversations/{conversation['id']}/runs").json()

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == "你好，测试完成"
    assert runs[0]["id"] == done["run_id"]
    assert runs[0]["status"] == "completed"
    assert [step["name"] for step in runs[0]["steps"]] == [
        "load_context",
        "call_llm",
        "finalize",
    ]
