"""Файл настроек pii-mask.toml: поиск, чтение секций, приоритет окружения в CLI."""
import argparse

import pytest

from pii_mask_enhanced import config
from pii_mask_enhanced.audit import OllamaAuditor
from pii_mask_enhanced.cli.cmd import CMD, CliError
from test_doc import _run_cli

TOML = """
[audit]
url = "http://10.0.0.5:11434"
model = "qwen3:4b"
timeout = 300

[convert]
soffice = "C:/LibreOffice/soffice.exe"
"""


@pytest.fixture
def no_user_config(monkeypatch, tmp_path):
    """Пользовательский конфиг машины, где идут тесты, не должен попадать в тест."""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "нет" / "config.toml")
    monkeypatch.chdir(tmp_path)


def test_explicit_path_must_exist(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.find_config(tmp_path / "нет.toml")


def test_file_in_current_directory_is_found(tmp_path, no_user_config):
    (tmp_path / "pii-mask.toml").write_text(TOML, encoding="utf-8")
    assert config.load_section("convert") == {"soffice": "C:/LibreOffice/soffice.exe"}


def test_user_config_is_found(tmp_path, monkeypatch):
    user = tmp_path / "user" / "config.toml"
    user.parent.mkdir()
    user.write_text(TOML, encoding="utf-8")
    monkeypatch.setattr(config, "user_config_path", lambda: user)
    monkeypatch.chdir(tmp_path)
    assert config.load_section("audit")["model"] == "qwen3:4b"


def test_no_file_means_empty_section(no_user_config):
    assert config.load_section("audit") == {}


def test_broken_file_is_named(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[audit\nurl = ", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.toml"):
        config.load_section("audit", path)


def test_auditor_from_config_with_overrides(tmp_path):
    path = tmp_path / "pii-mask.toml"
    path.write_text(TOML, encoding="utf-8")
    auditor = OllamaAuditor.from_config(path, model="qwen3:8b")
    assert (auditor.url, auditor.model, auditor.timeout) == ("http://10.0.0.5:11434", "qwen3:8b", 300)


def test_auditor_rejects_unknown_setting(tmp_path):
    path = tmp_path / "pii-mask.toml"
    path.write_text('[audit]\nmodle = "опечатка"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="modle"):
        OllamaAuditor.from_config(path)


def test_cli_environment_wins_over_file(tmp_path, monkeypatch):
    """Порядок в CLI: окружение -> файл -> значение по умолчанию."""
    path = tmp_path / "pii-mask.toml"
    path.write_text(TOML, encoding="utf-8")
    monkeypatch.setenv("PII_MASK_OLLAMA_URL", "http://env:11434")
    monkeypatch.delenv("PII_MASK_AUDITOR_MODEL", raising=False)
    auditor = CMD._auditor(argparse.Namespace(config=str(path)))
    assert (auditor.url, auditor.model, auditor.keep_alive) == ("http://env:11434", "qwen3:4b", "60s")


def test_cli_unknown_setting_is_an_error(tmp_path):
    path = tmp_path / "pii-mask.toml"
    path.write_text('[audit]\nmodle = "опечатка"\n', encoding="utf-8")
    with pytest.raises(CliError, match="modle"):
        CMD._auditor(argparse.Namespace(config=str(path)))


def test_cli_missing_config_file(tmp_path, capsys):
    src = tmp_path / "a.txt"
    src.write_text("текст", encoding="utf-8")
    assert _run_cli(["mask", str(src), "--audit", "--config", str(tmp_path / "нет.toml")]) == 2
    assert "не найден" in capsys.readouterr().err
