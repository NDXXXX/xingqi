"""CLI parsing and exit behavior."""

from types import SimpleNamespace
import sqlite3

from zhiyu.cli import main as cli
from zhiyu.cli.commands import chat, characters, providers
from zhiyu.application.data_archive import DataArchiveService


def test_doctor_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(cli, "run_checks", lambda: [])
    assert cli.run(["doctor"]) == 0
    assert capsys.readouterr().err == ""


def test_configuration_error_has_stable_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(providers.ProviderService, "set_default", lambda *_args: (_ for _ in ()).throw(ValueError("bad")))
    assert cli.run(["provider", "default", "missing", "model"]) == 2
    assert "配置错误" in capsys.readouterr().err


def test_serve_rejects_non_loopback_host(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)

    assert cli.run(["serve", "--host", "0.0.0.0"]) == 2
    assert "仅允许监听本机回环地址" in capsys.readouterr().err


def test_keyless_custom_base_url_provider_can_be_added_noninteractively(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(providers.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(providers, "getpass", lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected prompt")))
    monkeypatch.setattr(
        providers.ProviderService,
        "add",
        lambda _self, **values: captured.update(values) or SimpleNamespace(name=values["name"], models=[]),
    )

    assert cli.run([
        "provider", "add", "local", "--type", "openai",
        "--base-url", "http://127.0.0.1:11434/v1",
    ]) == 0
    assert captured["api_key"] is None
    assert captured["base_url"] == "http://127.0.0.1:11434/v1"
    assert "已添加 local" in capsys.readouterr().out


def test_cli_data_restore_builds_a_separate_data_directory(tmp_path, monkeypatch, capsys):
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE items (name TEXT)")
        db.execute("INSERT INTO items VALUES ('keep')")
    service = DataArchiveService(database, tmp_path / "memory", tmp_path / "avatars")
    archive = service.create(tmp_path / "backup.zip")
    monkeypatch.setattr(cli, "upgrade_database", lambda: (_ for _ in ()).throw(AssertionError("restore must not touch active DB")))
    target = tmp_path / "restored"
    assert cli.run(["data", "restore", str(archive), "--target", str(target)]) == 0
    with sqlite3.connect(target / "companion.db") as db:
        assert db.execute("SELECT name FROM items").fetchone()[0] == "keep"
    assert "已恢复到" in capsys.readouterr().out


class _StubCharacterService:
    def __init__(self, **overrides):
        self.created: dict | None = None
        for name, value in overrides.items():
            setattr(self, name, value)

    def list(self):
        return []

    def create(self, **fields):
        self.created = fields
        return type("Character", (), {"id": "c1", "name": fields["name"]})()

    def delete(self, character_id):
        raise ValueError("角色不存在")


def test_character_list_on_empty_database(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(characters, "CharacterService", _StubCharacterService)

    assert cli.run(["character", "list"]) == 0
    assert "尚未创建角色" in capsys.readouterr().out


def test_character_delete_missing_has_stable_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(characters, "CharacterService", _StubCharacterService)

    assert cli.run(["character", "delete", "missing"]) == 2
    assert "配置错误" in capsys.readouterr().err


def test_character_add_warns_when_system_prompt_covers_fields(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    service = _StubCharacterService()
    monkeypatch.setattr(characters, "CharacterService", lambda: service)

    assert cli.run(["character", "add", "--name", "Luna", "--personality", "温柔", "--system-prompt", "只回英文"]) == 0

    captured = capsys.readouterr()
    assert "不会生效" in captured.err
    assert "已创建 Luna" in captured.out
    assert "只回英文" not in captured.out


def test_chat_repl_routes_bare_character_command(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(chat, "_entry_state", lambda _args: (None, None, []))
    answers = iter(["/character", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.run(["chat"]) == 0
    assert "当前还没有会话" in capsys.readouterr().out


def test_chat_verbose_command_switches_and_rejects(monkeypatch, capsys):
    monkeypatch.setattr(cli, "upgrade_database", lambda: None)
    monkeypatch.setattr(chat, "_entry_state", lambda _args: (None, None, []))
    answers = iter(["/verbose on", "/verbose bad", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert cli.run(["chat"]) == 0

    captured = capsys.readouterr()
    assert "verbose=on" in captured.out
    assert "用法：/verbose on|full|off" in captured.err
