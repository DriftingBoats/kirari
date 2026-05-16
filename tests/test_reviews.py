from __future__ import annotations

import importlib
import json
import time
import asyncio


def test_promise_review_writes_pinned_file(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HERMES_GATEWAY_SERVICE", "")

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.main as main

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(main)

    database.init_db()
    memory_files.ensure_memory_files()
    now = time.time()
    with database.db() as conn:
        conn.execute(
            """
            INSERT INTO pending_reviews(id, kind, payload_json, reason, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                "review_promise",
                "promise",
                json.dumps({"kind": "promise", "text": "Always ask before changing SOUL.md."}),
                "boundary-like promise",
                "pending",
                now,
                now,
            ),
        )

    asyncio.run(main.review_action("review_promise", main.ReviewAction(action="approve")))

    assert "Always ask before changing SOUL.md." in memory_files.read_memory_file("PINNED.md")
    assert "Always ask before changing SOUL.md." not in memory_files.read_memory_file("MEMORY.md")
