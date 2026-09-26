"""Provider CRUD、默认模型和统一错误响应测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.errors import install_error_handlers
from app.api.providers import router as providers_router
from app.api.settings import router as settings_router
from app.database import models  # noqa: F401
from app.database.db import Base, get_db


def _client(monkeypatch) -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    secrets: dict[str, str] = {}

    monkeypatch.setattr("app.api.providers.keystore.set", secrets.__setitem__)
    monkeypatch.setattr("app.api.providers.keystore.get", secrets.get)
    monkeypatch.setattr("app.api.providers.keystore.delete", lambda ref: secrets.pop(ref, None))
    monkeypatch.setattr("app.providers.router.keystore.get", secrets.get)

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(providers_router)
    app.include_router(settings_router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_provider_crud_models_and_default(monkeypatch):
    with _client(monkeypatch) as client:
        created = client.post(
            "/api/providers",
            json={"name": "Work", "provider_type": "deepseek", "api_key": "secret"},
        )
        assert created.status_code == 201
        provider = created.json()
        assert provider["configured"] is True
        assert len(provider["models"]) == 2

        updated = client.patch(
            f"/api/providers/{provider['id']}",
            json={"name": "Work AI", "enabled": False},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Work AI"
        assert updated.json()["enabled"] is False

        model = client.post(
            f"/api/providers/{provider['id']}/models",
            json={"model_name": "custom", "display_name": "Custom"},
        ).json()
        assert model["model_name"] == "custom"

        assert client.put(
            "/api/settings/default-model",
            json={"provider_id": provider["id"], "model_id": model["id"]},
        ).status_code == 200
        assert client.delete(f"/api/providers/{provider['id']}").status_code == 409

        assert client.put(
            "/api/settings/default-model",
            json={"provider_id": None, "model_id": None},
        ).status_code == 200
        assert client.delete(f"/api/providers/{provider['id']}").status_code == 204


def test_duplicate_provider_uses_standard_error(monkeypatch):
    with _client(monkeypatch) as client:
        payload = {"name": "Same", "provider_type": "openai", "api_key": "secret"}
        assert client.post("/api/providers", json=payload).status_code == 201
        response = client.post("/api/providers", json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert response.json()["error"]["message"] == "Provider 名称已存在"
