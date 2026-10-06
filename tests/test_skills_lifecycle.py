"""Persistent Skills lifecycle behavior."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from zhiyu.application.skills import SkillService
from zhiyu.infrastructure.database.db import Base


def _write_skill(root, name="example", body="version one"):
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.mkdir()
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Example skill\nversion: 1.0\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def test_local_skill_install_disable_remove_and_restore(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    source = _write_skill(tmp_path / "source")
    service = SkillService(sessions, tmp_path / "managed")

    installed = service.install(source)
    assert installed["name"] == "example"
    assert installed["managed"] is True
    assert service.enabled_overrides() == {"example": True}

    service.enable("example", False)
    assert service.enabled_overrides() == {"example": False}
    assert service.show("example")["enabled"] is False

    trash_path = service.remove("example")
    assert trash_path.exists()
    assert service.enabled_overrides() == {}
    restored_path = service.restore("example")
    assert restored_path == tmp_path / "managed" / "example"
    assert restored_path.exists()
    assert service.enabled_overrides() == {"example": False}


def test_skill_update_requires_explicit_apply_and_archives_previous(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    source = _write_skill(tmp_path / "source")
    service = SkillService(sessions, tmp_path / "managed")
    service.install(source)
    original_hash = service.show("example")["content_hash"]

    (source / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example skill\nversion: 2.0\n---\n\nversion two",
        encoding="utf-8",
    )
    preview = service.update("example")
    assert preview["changed"] is True
    assert preview["applied"] is False
    assert service.show("example")["content_hash"] == original_hash

    result = service.update("example", apply=True)
    assert result["applied"] is True
    assert result["new_hash"] != original_hash
    assert len(list((tmp_path / "managed" / ".history" / "example").iterdir())) == 1


def test_register_existing_skill_records_metadata_without_moving_files(tmp_path):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    skills_dir = tmp_path / "skills"
    source = _write_skill(skills_dir)
    service = SkillService(sessions, skills_dir)

    assert service.register_existing() == 1
    assert service.register_existing() == 0
    item = service.show("example")
    assert item["managed"] is True
    assert item["modified"] is False
    assert Path(item["path"]) == source
