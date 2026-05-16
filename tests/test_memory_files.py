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
    assert memory_files.memory_file_path("SOUL.md") == tmp_path / "hermes" / "SOUL.md"
    assert memory_files.memory_file_path("MEMORY.md") == tmp_path / "hermes" / "memories" / "MEMORY.md"


def test_hermes_context_file_syncs_companion_files(tmp_path, monkeypatch):
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
    memory_files.write_memory_file("PINNED.md", "# PINNED\n\nAlways keep the promise.")
    memory_files.write_memory_file("DREAM.md", "# DREAM\n\nToday felt warmer.")

    generated = tmp_path / "hermes" / "HERMES.md"
    text = generated.read_text(encoding="utf-8")
    assert "## PINNED.md" in text
    assert "Always keep the promise." in text
    assert "## DREAM.md" in text
    assert "Today felt warmer." in text


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


def test_memory_file_versions_restore(tmp_path, monkeypatch):
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
    memory_files.write_memory_file("MEMORY.md", "# MEMORY\n\nfirst")
    memory_files.write_memory_file("MEMORY.md", "# MEMORY\n\nsecond")

    versions = memory_files.list_file_versions("MEMORY.md")
    assert len(versions) == 2
    memory_files.restore_file_version("MEMORY.md", versions[0]["id"])
    assert "first" in memory_files.read_memory_file("MEMORY.md")
