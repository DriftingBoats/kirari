from __future__ import annotations

import importlib


def test_memory_files_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
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
    assert memory_files.memory_file_path("SOUL.md") == tmp_path / "memory" / "SOUL.md"
    assert memory_files.memory_file_path("MEMORY.md") == tmp_path / "memory" / "MEMORY.md"


def test_companion_bundle_contains_pinned_and_dream_context(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
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

    text = memory_files.file_bundle()
    assert "===== PINNED.md =====" in text
    assert "Always keep the promise." in text
    assert "===== DREAM.md =====" in text
    assert "Today felt warmer." in text


def test_unknown_memory_file_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
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
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
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


def test_indexed_memory_block_can_be_updated_and_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
    import app.config as config
    import app.db as database
    import app.memory_files as memory_files

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)

    database.init_db()
    memory_files.ensure_memory_files()
    memory_files.upsert_memory_block("mem_1", "Favorite", "likes tea")
    memory_files.upsert_memory_block("mem_1", "Favorite", "likes coffee")
    text = memory_files.read_memory_file("MEMORY.md")
    assert "likes coffee" in text
    assert "likes tea" not in text
    assert text.count("kirari-memory:mem_1") == 2

    assert memory_files.remove_memory_block("mem_1")
    assert "likes coffee" not in memory_files.read_memory_file("MEMORY.md")
