from __future__ import annotations

import importlib
import asyncio
from types import SimpleNamespace


class FakeRequest:
    def __init__(self, path: str, key: str = ""):
        self.url = SimpleNamespace(path=path)
        self.headers = {"x-kirari-key": key} if key else {}
        self.query_params = {}
        self.cookies = {}


def test_api_requires_access_key_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("KIRARI_ACCESS_KEY", "test-key")

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.main as main

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(main)

    assert asyncio.run(main.auth_status()) == {"required": True}

    async def call_next(_request):
        return SimpleNamespace(status_code=200)

    denied = asyncio.run(main.require_access_key(FakeRequest("/api/status"), call_next))
    assert denied.status_code == 401

    allowed = asyncio.run(main.require_access_key(FakeRequest("/api/status", "test-key"), call_next))
    assert allowed.status_code == 200
