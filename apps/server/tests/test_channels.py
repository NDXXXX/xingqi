"""Channels 测试：IncomingMessage + Conversation 外部映射。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.channels.base import IncomingMessage
from app.database import models  # noqa: F401  注册 ORM 模型
from app.database.db import Base
from app.database.repositories.conversation_repository import ConversationRepository


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
    repo.create(db, title="c1", channel="desktop")
    qq = repo.create(db, title="qq chat", channel="qq", external_user_id="123")
    assert repo.get_by_external(db, "qq", "123").id == qq.id
    assert repo.get_by_external(db, "qq", "999") is None
    assert repo.get_by_external(db, "desktop", "123") is None
    db.close()
