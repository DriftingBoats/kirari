from __future__ import annotations

import asyncio
import importlib
import time


def _reload_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.agent as agent
    import app.companion as companion
    import app.telegram as telegram

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(agent)
    importlib.reload(companion)
    importlib.reload(telegram)
    database.init_db()
    memory_files.ensure_memory_files()
    return config, database, agent, companion, telegram


def test_subscription_environment_removes_api_keys(tmp_path, monkeypatch):
    _, _, agent, _, _ = _reload_runtime(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-be-used")

    env = agent._clean_subscription_env()

    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env


def test_telegram_inbound_message_is_deduplicated(tmp_path, monkeypatch):
    _, _, _, _, telegram = _reload_runtime(tmp_path, monkeypatch)
    first = telegram.save_telegram_message(
        telegram_message_id=7,
        chat_id=42,
        user_id=42,
        direction="in",
        text="hello",
    )
    duplicate = telegram.save_telegram_message(
        telegram_message_id=7,
        chat_id=42,
        user_id=42,
        direction="in",
        text="hello",
    )

    assert isinstance(first, int)
    assert duplicate is None
    assert len(telegram._message_chunks("x" * 8001)) == 3


def test_companion_reply_creates_review_instead_of_action(tmp_path, monkeypatch):
    _, database, agent, companion, _ = _reload_runtime(tmp_path, monkeypatch)

    async def fake_agent(_prompt, _schema):
        return agent.AgentResult(
            ok=True,
            text="{}",
            data={
                "reply": "我先把提醒放到待确认里。",
                "review_items": [
                    {
                        "kind": "reminder",
                        "title": "喝水",
                        "text": "提醒我喝水",
                        "reason": "user requested a reminder",
                        "when": "2030-01-01T09:00:00+08:00",
                        "repeat_rule": "daily",
                        "layer": "life",
                    }
                ],
            },
        )

    monkeypatch.setattr(companion, "ask_agent_json", fake_agent)
    result = asyncio.run(companion.generate_companion_reply("每天九点提醒我喝水"))

    assert result.ok
    assert len(result.data["review_ids"]) == 1
    with database.db() as conn:
        row = conn.execute("SELECT kind, status FROM pending_reviews").fetchone()
    assert dict(row) == {"kind": "reminder", "status": "pending"}


def test_repeating_reminder_advances_and_snooze_resets(tmp_path, monkeypatch):
    config, database, _, _, _ = _reload_runtime(tmp_path, monkeypatch)
    import app.reminders as reminders

    importlib.reload(reminders)
    future = time.time() + 3600
    now = time.time()
    with database.db() as conn:
        conn.execute(
            """
            INSERT INTO reminders(id, title, remind_at, repeat_rule, status, source, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            ("repeat", "daily", future, "daily", "pending", "test", now, now),
        )

    reminders.mark_sent("repeat")
    with database.db() as conn:
        row = conn.execute("SELECT remind_at, status, sent_at FROM reminders WHERE id='repeat'").fetchone()
    assert row["status"] == "pending"
    assert row["sent_at"] is None
    assert abs(float(row["remind_at"]) - (future + 86400)) < 1

    assert reminders.snooze("repeat", 600)
    with database.db() as conn:
        snoozed = conn.execute("SELECT remind_at FROM reminders WHERE id='repeat'").fetchone()
    assert 540 < float(snoozed["remind_at"]) - time.time() <= 600


def test_chinese_memory_tokenization_uses_bigrams():
    from app.retrieval import _tokens

    assert {"喜欢", "欢喝", "喝茶"}.issubset(_tokens("喜欢喝茶"))
