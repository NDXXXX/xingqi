"""Channels 测试：IncomingMessage + Conversation 外部映射。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.channels import ChannelService
from zhiyu.channels.base import IncomingMessage
from zhiyu.infrastructure.database import models  # noqa: F401  注册 ORM 模型
from zhiyu.infrastructure.database.db import Base
from zhiyu.infrastructure.database.repositories.conversation_repository import ConversationRepository


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_incoming_message():
    m = IncomingMessage(channel="qq", external_user_id="123", external_conversation_id="123", text="你好")
    assert m.channel == "qq"
    assert m.text == "你好"
    assert m.metadata == {}


def test_get_by_external():
    db = _session()
    repo = ConversationRepository()
    repo.create(db, title="c1", channel="local")
    qq = repo.create(db, title="qq chat", channel="qq", external_user_id="123")
    assert repo.get_by_external(db, "qq", "123").id == qq.id
    assert repo.get_by_external(db, "qq", "999") is None
    assert repo.get_by_external(db, "local", "123") is None
    db.close()


def test_configure_qq_can_clear_existing_token():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    class Secrets:
        def __init__(self):
            self.deleted = []

        def set(self, _reference, _value):
            pass

        def delete(self, reference):
            self.deleted.append(reference)

    secrets = Secrets()
    service = ChannelService(session_factory=session_factory, secrets=secrets)
    service.configure_qq("ws://127.0.0.1:6199/ws", token="secret")
    with session_factory() as db:
        old_ref = service.configs.get(db, "qq").secret_ref

    service.configure_qq("ws://127.0.0.1:6199/ws", clear_token=True)

    with session_factory() as db:
        assert service.configs.get(db, "qq").secret_ref is None
    assert secrets.deleted == [old_ref]
