from __future__ import annotations

import asyncio
import importlib
import json
import time


def _load(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("GEMINI_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("CODEX_MEMORY_RERANK", "false")

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.memory_store as memory_store
    import app.embeddings as embeddings
    import app.retrieval as retrieval
    import app.memory_service as memory_service
    import app.memory_lifecycle as lifecycle

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(memory_store)
    importlib.reload(embeddings)
    importlib.reload(retrieval)
    importlib.reload(memory_service)
    importlib.reload(lifecycle)
    database.init_db()
    memory_files.ensure_memory_files()
    memory_store.ensure_bucket_dirs()
    return database, memory_store, memory_service, retrieval, lifecycle


def test_bucket_markdown_is_canonical_and_rebuilds_projection(tmp_path, monkeypatch):
    database, store, service, _, _ = _load(tmp_path, monkeypatch)
    saved = asyncio.run(
        service.save_memory_candidate(
            {
                "id": "mem_trip",
                "type": "event",
                "title": "海边散步",
                "text": "我们在青岛海边散步。",
                "domains": ["life"],
                "tags": ["旅行"],
            },
            source_message_ids=[11, 12],
        )
    )["item"]
    path = store.find_bucket_paths("mem_trip")[0]
    assert "active" in path.parts
    assert path.read_text(encoding="utf-8").startswith("---\n")
    assert store.read_bucket(path)["source_message_ids"] == [11, 12]
    assert saved["footprints"][0]["action"] == "created"

    with database.db() as conn:
        conn.execute("DELETE FROM memory_items WHERE id='mem_trip'")
    store.reconcile_memory_store()
    with database.db() as conn:
        row = conn.execute("SELECT text, source_message_ids FROM memory_items WHERE id='mem_trip'").fetchone()
    assert row["text"] == "我们在青岛海边散步。"
    assert json.loads(row["source_message_ids"]) == [11, 12]


def test_similar_writes_merge_with_lineage_and_sources(tmp_path, monkeypatch):
    database, store, service, _, _ = _load(tmp_path, monkeypatch)
    asyncio.run(
        service.save_memory_candidate(
            {"id": "mem_a", "type": "event", "title": "攀岩", "text": "每周六下午去城西抱石馆攀岩。"},
            source_message_ids=[1],
        )
    )
    result = asyncio.run(
        service.save_memory_candidate(
            {"id": "mem_b", "type": "event", "title": "周末运动", "text": "每周六下午我会去城西抱石馆攀岩。"},
            source_message_ids=[2],
        )
    )
    assert result["created"] is False
    assert result["merged_into"] == "mem_a"
    with database.db() as conn:
        rows = conn.execute("SELECT * FROM memory_items").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["source_message_ids"]) == [1, 2]
    bucket = store.read_bucket(store.find_bucket_paths("mem_a")[0])
    assert bucket["lineage"]["merged_from"][0]["incoming_id"] == "mem_b"
    assert any(mark["action"] == "merged" for mark in bucket["footprints"])


def test_archive_is_searchable_restore_moves_bucket_and_delete_tombstones(tmp_path, monkeypatch):
    database, store, service, retrieval, _ = _load(tmp_path, monkeypatch)
    asyncio.run(
        service.save_memory_candidate(
            {"id": "mem_tea", "type": "fact", "title": "饮品", "text": "最喜欢桂花乌龙茶。"}
        )
    )
    service.archive_memory("mem_tea", reason="test")
    assert "archive" in store.find_bucket_paths("mem_tea")[0].parts
    found = retrieval.recall_memories("桂花乌龙", include_archived=True)
    assert found[0]["id"] == "mem_tea" and found[0]["archived"] == 1

    service.restore_memory("mem_tea")
    assert "active" in store.find_bucket_paths("mem_tea")[0].parts
    service.tombstone_memory("mem_tea")
    assert "tombstone" in store.find_bucket_paths("mem_tea")[0].parts
    with database.db() as conn:
        row = conn.execute("SELECT tombstoned, text FROM memory_items WHERE id='mem_tea'").fetchone()
    assert row["tombstoned"] == 1
    assert row["text"] == "最喜欢桂花乌龙茶。"
    assert retrieval.recall_memories("桂花乌龙", include_archived=True) == []


def test_used_memory_reinforces_and_creates_time_ripple(tmp_path, monkeypatch):
    database, _, service, _, _ = _load(tmp_path, monkeypatch)
    now = time.time()
    for memory_id, text in (("mem_used", "喜欢乌龙茶。"), ("mem_near", "那天一起买了茶。")):
        asyncio.run(
            service.save_memory_candidate(
                {"id": memory_id, "type": "event", "title": memory_id, "text": text, "created_at": now},
                allow_merge=False,
            )
        )

    import app.agent as agent
    import app.companion as companion

    importlib.reload(companion)

    async def fake_reply(_prompt, _schema):
        return agent.AgentResult(
            ok=True,
            text="{}",
            data={"reply": "我记得。", "review_items": [], "used_memory_ids": ["mem_used"]},
        )

    monkeypatch.setattr(companion, "ask_agent_json", fake_reply)
    result = asyncio.run(
        companion.generate_companion_reply(
            "我喜欢什么茶？",
            recalled_context="mem_used",
            recalled_items=[{"id": "mem_used"}],
        )
    )
    assert result.data["reinforced_memory_ids"] == ["mem_used"]
    with database.db() as conn:
        used = conn.execute("SELECT activation_count FROM memory_items WHERE id='mem_used'").fetchone()[0]
        near = conn.execute("SELECT activation_count FROM memory_items WHERE id='mem_near'").fetchone()[0]
    assert used == 1.0
    assert near == 0.3


def test_dream_creates_sourced_feel_and_deduplicated_event_buckets(tmp_path, monkeypatch):
    database, store, _, _, _ = _load(tmp_path, monkeypatch)
    now = time.time()
    with database.db() as conn:
        conn.execute(
            """
            INSERT INTO telegram_messages(chat_id, user_id, direction, text, raw_json, created_at)
            VALUES(-1, 0, 'in', '今天去看海了', '{}', ?)
            """,
            (now,),
        )
        conn.execute(
            """
            INSERT INTO telegram_messages(chat_id, user_id, direction, text, raw_json, created_at)
            VALUES(-1, 0, 'out', '那一定很舒服', '{}', ?)
            """,
            (now + 1,),
        )

    import app.agent as agent
    import app.dream as dream

    importlib.reload(dream)

    async def fake_dream(_prompt, _schema):
        return agent.AgentResult(
            ok=True,
            text="{}",
            data={
                "summary": "今天一起聊了海。",
                "feel": "我感到这段分享很轻盈。",
                "feel_valence": 0.82,
                "feel_arousal": 0.35,
                "low_risk_memories": [
                    {
                        "type": "event", "title": "看海", "text": "今天去看海了。",
                        "importance": 0.6, "emotional_weight": 0.35,
                        "valence": 0.82, "arousal": 0.35, "summary": "今天看海",
                        "domains": ["life"], "tags": ["海边"], "entities": [],
                        "why_remembered": "这是今天分享的重要经历。",
                    }
                ],
                "review_items": [],
                "board_message": "",
            },
        )

    monkeypatch.setattr(dream, "ask_agent_json", fake_dream)
    assert asyncio.run(dream.run_dream("test"))["ok"] is True
    with database.db() as conn:
        rows = conn.execute(
            "SELECT type, source_message_ids, valence, arousal FROM memory_items ORDER BY type"
        ).fetchall()
    assert {row["type"] for row in rows} == {"event", "feel"}
    assert all(json.loads(row["source_message_ids"]) == [1, 2] for row in rows)
    feel = next(row for row in rows if row["type"] == "feel")
    assert feel["valence"] == 0.82 and feel["arousal"] == 0.35
    assert len(list(store.iter_buckets(["active"]))) == 2
