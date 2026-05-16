from __future__ import annotations

import importlib
import json


def test_import_hermes_telegram_sessions_dedupes(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    import app.config as config
    import app.db as database
    import app.hermes_sessions as hermes_sessions

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(hermes_sessions)

    sessions_dir = tmp_path / "hermes" / "sessions"
    sessions_dir.mkdir(parents=True)
    session_id = "20260516_204203_abc123"
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                "agent:main:telegram:dm:100": {
                    "session_id": session_id,
                    "platform": "telegram",
                    "origin": {
                        "platform": "telegram",
                        "chat_id": "100",
                        "user_id": "100",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (sessions_dir / f"{session_id}.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"role": "session_meta", "platform": "telegram"}),
                json.dumps({"role": "user", "content": "hello", "timestamp": "2026-05-16T20:42:08"}),
                json.dumps({"role": "assistant", "content": "hi", "timestamp": "2026-05-16T20:42:09"}),
            ]
        ),
        encoding="utf-8",
    )

    database.init_db()
    first = hermes_sessions.import_hermes_telegram_sessions()
    second = hermes_sessions.import_hermes_telegram_sessions()

    assert first["messages"] == 2
    assert second["messages"] == 0
    with database.db() as conn:
        rows = conn.execute("SELECT direction, text FROM telegram_messages ORDER BY created_at ASC").fetchall()
    assert [(row["direction"], row["text"]) for row in rows] == [("in", "hello"), ("out", "hi")]
