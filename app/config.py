from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv_ints(*names: str) -> set[int]:
    raw = ""
    for name in names:
        raw = os.getenv(name, "").strip()
        if raw:
            break
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            continue
    return ids


class Settings(BaseModel):
    app_host: str = Field(default_factory=lambda: os.getenv("APP_HOST", "0.0.0.0"))
    app_port: int = Field(default_factory=lambda: _int_env("APP_PORT", 8080))
    base_url: str = Field(default_factory=lambda: os.getenv("BASE_URL", "http://127.0.0.1:8080"))
    app_data_dir: Path = Field(default_factory=lambda: Path(os.getenv("APP_DATA_DIR", "./data")).expanduser())
    access_key: str = Field(default_factory=lambda: os.getenv("KIRARI_ACCESS_KEY", os.getenv("APP_ACCESS_KEY", "")))

    telegram_bot_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_allowed_user_ids: set[int] = Field(
        default_factory=lambda: _csv_ints("TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ALLOWED_USERS")
    )
    telegram_webhook_secret: str = Field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_SECRET", ""))
    telegram_webapp_auth_max_age_seconds: int = Field(
        default_factory=lambda: _int_env("TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS", 604800)
    )

    hermes_bin: str = Field(default_factory=lambda: os.getenv("HERMES_BIN", "hermes"))
    hermes_home: Path = Field(default_factory=lambda: Path(os.getenv("HERMES_HOME", "~/.hermes")).expanduser())
    hermes_provider: str = Field(default_factory=lambda: os.getenv("HERMES_PROVIDER", ""))
    hermes_model: str = Field(default_factory=lambda: os.getenv("HERMES_MODEL", ""))
    hermes_timeout_seconds: int = Field(default_factory=lambda: _int_env("HERMES_TIMEOUT_SECONDS", 180))
    hermes_dry_run: bool = Field(default_factory=lambda: _bool_env("HERMES_DRY_RUN", False))

    dream_hour: int = Field(default_factory=lambda: _int_env("DREAM_HOUR", 4))
    recent_message_limit: int = Field(default_factory=lambda: _int_env("RECENT_MESSAGE_LIMIT", 24))

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "aion.sqlite3"

    @property
    def memory_dir(self) -> Path:
        return self.hermes_home / "memories"


settings = Settings()
