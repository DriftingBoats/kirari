from __future__ import annotations

import importlib


def test_memory_files_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    import app.config as config
    import app.db as database
    import app.memory_files as memory_files

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)

    database.init_db()
    memory_files.ensure_memory_files()
    memory_files.write_memory_file("SOUL.md", "# SOUL\n\nquiet devotion")
    assert "quiet devotion" in memory_files.read_memory_file("SOUL.md")


def test_unknown_memory_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    import app.config as config
    import app.memory_files as memory_files

    importlib.reload(config)
    importlib.reload(memory_files)

    try:
        memory_files.read_memory_file("../x")
    except ValueError:
        return
    raise AssertionError("unknown memory file should be rejected")
