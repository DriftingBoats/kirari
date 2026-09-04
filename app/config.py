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


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
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
    telegram_mode: str = Field(default_factory=lambda: os.getenv("TELEGRAM_MODE", "polling").strip().lower())
    telegram_poll_timeout_seconds: int = Field(
        default_factory=lambda: _int_env("TELEGRAM_POLL_TIMEOUT_SECONDS", 25)
    )
    telegram_webapp_auth_max_age_seconds: int = Field(
        default_factory=lambda: _int_env("TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS", 604800)
    )

    codex_bin: str = Field(default_factory=lambda: os.getenv("CODEX_BIN", "codex"))
    codex_home: Path | None = Field(
        default_factory=lambda: Path(os.environ["KIRARI_CODEX_HOME"]).expanduser()
        if os.getenv("KIRARI_CODEX_HOME")
        else None
    )
    codex_model: str = Field(default_factory=lambda: os.getenv("CODEX_MODEL", ""))
    codex_reasoning_effort: str = Field(default_factory=lambda: os.getenv("CODEX_REASONING_EFFORT", "low"))
    codex_timeout_seconds: int = Field(default_factory=lambda: _int_env("CODEX_TIMEOUT_SECONDS", 240))
    codex_dry_run: bool = Field(default_factory=lambda: _bool_env("CODEX_DRY_RUN", False))

    dream_hour: int = Field(default_factory=lambda: _int_env("DREAM_HOUR", 4))
    dream_schedule_enabled: bool = Field(default_factory=lambda: _bool_env("DREAM_SCHEDULE_ENABLED", False))
    recent_message_limit: int = Field(default_factory=lambda: _int_env("RECENT_MESSAGE_LIMIT", 24))
    app_timezone: str = Field(default_factory=lambda: os.getenv("APP_TIMEZONE", "Asia/Shanghai"))

    codex_memory_rerank: bool = Field(
        default_factory=lambda: _bool_env("CODEX_MEMORY_RERANK", True)
    )
    gemini_embedding_enabled: bool = Field(
        default_factory=lambda: _bool_env("GEMINI_EMBEDDING_ENABLED", True)
    )
    gemini_embedding_api_key: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_EMBEDDING_API_KEY", os.getenv("GEMINI_API_KEY", "")
        ).strip()
    )
    gemini_embedding_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001").strip()
    )
    gemini_embedding_dimensions: int = Field(
        default_factory=lambda: _int_env("GEMINI_EMBEDDING_DIMENSIONS", 768)
    )
    gemini_embedding_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_EMBEDDING_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
    )
    gemini_embedding_timeout_seconds: float = Field(
        default_factory=lambda: _float_env("GEMINI_EMBEDDING_TIMEOUT_SECONDS", 30.0)
    )
    gemini_embedding_retry_base_seconds: float = Field(
        default_factory=lambda: _float_env("GEMINI_EMBEDDING_RETRY_BASE_SECONDS", 5.0)
    )
    gemini_embedding_retry_max_seconds: float = Field(
        default_factory=lambda: _float_env("GEMINI_EMBEDDING_RETRY_MAX_SECONDS", 300.0)
    )
    gemini_embedding_poll_seconds: float = Field(
        default_factory=lambda: _float_env("GEMINI_EMBEDDING_POLL_SECONDS", 3.0)
    )
    memory_vector_threshold: float = Field(
        default_factory=lambda: _float_env("MEMORY_VECTOR_THRESHOLD", 0.55)
    )
    memory_merge_threshold: float = Field(
        default_factory=lambda: _float_env("MEMORY_MERGE_THRESHOLD", 0.82)
    )
    memory_surface_idle_hours: float = Field(
        default_factory=lambda: _float_env("MEMORY_SURFACE_IDLE_HOURS", 6.0)
    )
    memory_surface_limit: int = Field(
        default_factory=lambda: _int_env("MEMORY_SURFACE_LIMIT", 3)
    )
    memory_catalog_limit: int = Field(
        default_factory=lambda: _int_env("MEMORY_CATALOG_LIMIT", 240)
    )
    memory_decay_lambda: float = Field(
        default_factory=lambda: _float_env("MEMORY_DECAY_LAMBDA", 0.05)
    )
    memory_decay_enabled: bool = Field(
        default_factory=lambda: _bool_env("MEMORY_DECAY_ENABLED", True)
    )
    memory_decay_threshold: float = Field(
        default_factory=lambda: _float_env("MEMORY_DECAY_THRESHOLD", 0.03)
    )
    memory_decay_interval_hours: float = Field(
        default_factory=lambda: _float_env("MEMORY_DECAY_INTERVAL_HOURS", 24.0)
    )

    proactive_enabled: bool = Field(default_factory=lambda: _bool_env("PROACTIVE_ENABLED", False))
    proactive_idle_hours: float = Field(default_factory=lambda: _float_env("PROACTIVE_IDLE_HOURS", 18.0))
    proactive_cooldown_hours: float = Field(default_factory=lambda: _float_env("PROACTIVE_COOLDOWN_HOURS", 24.0))
    proactive_quiet_start: int = Field(default_factory=lambda: _int_env("PROACTIVE_QUIET_START", 23))
    proactive_quiet_end: int = Field(default_factory=lambda: _int_env("PROACTIVE_QUIET_END", 8))

    @property
    def db_path(self) -> Path:
        return self.app_data_dir / "kirari.sqlite3"

    @property
    def memory_dir(self) -> Path:
        configured = os.getenv("KIRARI_MEMORY_DIR")
        return Path(configured).expanduser() if configured else self.app_data_dir / "memory"


settings = Settings()
