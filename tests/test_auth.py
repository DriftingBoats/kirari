from __future__ import annotations

import importlib
import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlencode
from types import SimpleNamespace


class FakeRequest:
    def __init__(self, path: str, key: str = "", telegram_init_data: str = ""):
        self.url = SimpleNamespace(path=path)
        self.headers = {"x-kirari-key": key} if key else {}
        if telegram_init_data:
            self.headers["x-telegram-init-data"] = telegram_init_data
        self.query_params = {}
        self.cookies = {}


def signed_init_data(bot_token: str, user_id: int, auth_date: int = 1_700_000_000) -> str:
    payload = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps({"id": user_id, "first_name": "Kirari"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


def test_api_requires_access_key_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("KIRARI_ACCESS_KEY", "test-key")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USERS", raising=False)

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.main as main

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(main)

    assert asyncio.run(main.auth_status()) == {
        "required": True,
        "telegram_configured": False,
        "telegram_user_restricted": False,
    }

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    denied = asyncio.run(main.require_access_key(FakeRequest("/api/status"), call_next))
    assert denied.status_code == 401

    allowed = asyncio.run(main.require_access_key(FakeRequest("/api/status", "test-key"), call_next))
    assert allowed.status_code == 200


def test_api_accepts_valid_telegram_mini_app_init_data(tmp_path, monkeypatch):
    bot_token = "123456:test-token"
    init_data = signed_init_data(bot_token, user_id=42)
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.delenv("KIRARI_ACCESS_KEY", raising=False)
    monkeypatch.delenv("APP_ACCESS_KEY", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", bot_token)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "42")
    monkeypatch.setenv("TELEGRAM_WEBAPP_AUTH_MAX_AGE_SECONDS", "0")

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.main as main

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(main)

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    denied = asyncio.run(main.require_access_key(FakeRequest("/api/status"), call_next))
    assert denied.status_code == 401

    allowed = asyncio.run(main.require_access_key(FakeRequest("/api/status", telegram_init_data=init_data), call_next))
    assert allowed.status_code == 200
