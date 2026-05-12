from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_database_path() -> Path:
    override = os.getenv("JURIX_DB_PATH")
    if override:
        return Path(override)

    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "jurixmcp" / "jurix.db"
        return Path.home() / "AppData" / "Local" / "jurixmcp" / "jurix.db"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "jurixmcp" / "jurix.db"

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "jurixmcp" / "jurix.db"

    return Path.home() / ".local" / "share" / "jurixmcp" / "jurix.db"


@dataclass(slots=True)
class Settings:
    jurix_base_url: str = field(default_factory=lambda: os.getenv("JURIX_BASE_URL", "https://www.jurix.com.tr"))
    mailtm_base_url: str = field(default_factory=lambda: os.getenv("MAILTM_BASE_URL", "https://api.mail.tm"))
    database_path: Path = field(default_factory=_default_database_path)
    download_root: Path = field(default_factory=lambda: Path(os.getenv("JURIX_DOWNLOAD_DIR", "downloads")))
    default_user_agent: str = field(
        default_factory=lambda: os.getenv(
            "JURIX_USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
    )
    account_pool_target: int = field(default_factory=lambda: int(os.getenv("JURIX_POOL_TARGET", "3")))
    account_expiry_buffer_hours: int = field(
        default_factory=lambda: int(os.getenv("JURIX_EXPIRY_BUFFER_HOURS", "24"))
    )
    trial_days: int = field(default_factory=lambda: int(os.getenv("JURIX_TRIAL_DAYS", "7")))
    mail_poll_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("JURIX_MAIL_TIMEOUT_SECONDS", "120"))
    )
    mail_poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("JURIX_MAIL_INTERVAL_SECONDS", "5"))
    )


def get_settings() -> Settings:
    return Settings()
