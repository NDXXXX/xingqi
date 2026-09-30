"""Provider configuration through application services."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.providers import ProviderService
from zhiyu.infrastructure.database import models  # noqa: F401
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.setting_repository import SettingRepository


class FakeSecrets:
    def __init__(self):
        self.values = {}

    def set(self, ref, value):
        self.values[ref] = value

    def get(self, ref):
        return self.values.get(ref)

    def delete(self, ref):
        self.values.pop(ref, None)


def test_add_list_and_set_default_provider():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    service = ProviderService(sessions, FakeSecrets())

    created = service.add(name="Work", provider_type="deepseek", api_key="secret")
    assert created.configured is True
    assert service.list()[0].name == "Work"

    service.set_default("Work", created.models[0])
    with sessions() as db:
        default = SettingRepository().get(db, "default_model")
    assert default["provider_id"] == created.id
