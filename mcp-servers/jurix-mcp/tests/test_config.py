from pathlib import Path

from jurixmcp import config
from jurixmcp.config import get_settings


def test_get_settings_uses_global_database_path_on_macos(monkeypatch, tmp_path):
    monkeypatch.delenv("JURIX_DB_PATH", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    settings = get_settings()

    assert settings.database_path == tmp_path / "Library" / "Application Support" / "jurixmcp" / "jurix.db"


def test_get_settings_uses_xdg_data_home_when_available(monkeypatch, tmp_path):
    xdg_data_home = tmp_path / "xdg"
    monkeypatch.delenv("JURIX_DB_PATH", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data_home))
    monkeypatch.setattr(config.sys, "platform", "linux")

    settings = get_settings()

    assert settings.database_path == xdg_data_home / "jurixmcp" / "jurix.db"


def test_get_settings_prefers_explicit_database_override(monkeypatch, tmp_path):
    override = tmp_path / "custom" / "jurix.db"
    monkeypatch.setenv("JURIX_DB_PATH", str(override))

    settings = get_settings()

    assert settings.database_path == override
