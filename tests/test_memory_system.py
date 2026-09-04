from __future__ import annotations

import asyncio
import importlib
import time


def _load_memory_modules(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("CODEX_MEMORY_RERANK", "true")
    monkeypatch.setenv("GEMINI_EMBEDDING_API_KEY", "")
    monkeypatch.setenv("MEMORY_DECAY_THRESHOLD", "0.12")

    import app.config as config
    import app.db as database
    import app.memory_files as memory_files
    import app.retrieval as retrieval
    import app.memory_lifecycle as lifecycle

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(memory_files)
    importlib.reload(retrieval)
    importlib.reload(lifecycle)
    database.init_db()
    memory_files.ensure_memory_files()
    return database, memory_files, retrieval, lifecycle


def test_chinese_metadata_is_searchable_without_codex(tmp_path, monkeypatch):
    database, _, retrieval, _ = _load_memory_modules(tmp_path, monkeypatch)
    database.upsert_memory_item(
        {
            "id": "mem_climbing",
            "type": "event",
            "title": "周末运动",
            "text": "每周六会去城西运动馆。",
            "summary": "固定的周末运动习惯",
            "domains": ["生活"],
            "tags": ["抱石", "攀岩"],
            "entities": ["城西运动馆"],
            "importance": 0.6,
        }
    )

    results = retrieval.recall_memories("抱石")
    assert results[0]["id"] == "mem_climbing"
    with database.db() as conn:
        row = conn.execute(
            "SELECT activation_count FROM memory_items WHERE id='mem_climbing'"
        ).fetchone()
    assert row["activation_count"] == 0


def test_codex_subscription_can_recall_a_paraphrase(tmp_path, monkeypatch):
    database, _, retrieval, _ = _load_memory_modules(tmp_path, monkeypatch)
    database.upsert_memory_item(
        {
            "id": "mem_climbing",
            "type": "event",
            "title": "周六安排",
            "text": "每周六会去城西攀岩馆。",
            "importance": 0.7,
        }
    )

    import app.agent as agent

    async def fake_rerank(prompt, schema):
        return agent.AgentResult(
            ok=True,
            text="{}",
            data={
                "query_concepts": ["周末", "锻炼"],
                "query_valence": 0.6,
                "query_arousal": 0.4,
                "matches": [
                    {"id": "mem_climbing", "relevance": 0.93, "reason": "同一项固定运动安排"}
                ],
            },
        )

    monkeypatch.setattr(agent, "ask_agent_json", fake_rerank)
    results = asyncio.run(retrieval.recall_memories_with_codex("我周末一般怎么锻炼？"))
    assert results[0]["id"] == "mem_climbing"
    assert results[0]["_signals"]["mode"] == "codex-subscription-rerank"
    assert results[0]["_signals"]["semantic"] == 0.93


def test_decay_previews_then_archives_without_deleting(tmp_path, monkeypatch):
    database, memory_files, _, lifecycle = _load_memory_modules(tmp_path, monkeypatch)
    old = time.time() - 120 * 86400
    database.upsert_memory_item(
        {
            "id": "mem_old",
            "type": "event",
            "title": "旧小事",
            "text": "很久以前的一件低权重小事。",
            "importance": 0.01,
            "created_at": old,
            "updated_at": old,
            "last_active": old,
        }
    )
    memory_files.upsert_memory_block("mem_old", "旧小事", "很久以前的一件低权重小事。")

    preview = lifecycle.run_memory_decay(apply=False)
    assert preview["candidate_count"] == 1
    with database.db() as conn:
        assert conn.execute("SELECT archived FROM memory_items WHERE id='mem_old'").fetchone()[0] == 0

    applied = lifecycle.run_memory_decay(apply=True)
    assert applied["candidate_count"] == 1
    with database.db() as conn:
        row = conn.execute("SELECT archived, text FROM memory_items WHERE id='mem_old'").fetchone()
    assert row["archived"] == 1
    assert row["text"] == "很久以前的一件低权重小事。"
    assert "很久以前" not in memory_files.read_memory_file("MEMORY.md")


def test_reinforcement_is_explicit(tmp_path, monkeypatch):
    database, _, retrieval, _ = _load_memory_modules(tmp_path, monkeypatch)
    database.upsert_memory_item(
        {"id": "mem_useful", "type": "fact", "title": "饮品", "text": "喜欢乌龙茶。"}
    )
    retrieval.recall_memories("乌龙茶")
    with database.db() as conn:
        assert conn.execute(
            "SELECT activation_count FROM memory_items WHERE id='mem_useful'"
        ).fetchone()[0] == 0

    import app.main as main

    importlib.reload(main)
    asyncio.run(main.reinforce_memory("mem_useful"))
    with database.db() as conn:
        assert conn.execute(
            "SELECT activation_count FROM memory_items WHERE id='mem_useful'"
        ).fetchone()[0] == 1


def test_gemini_vectors_are_queued_and_used_for_paraphrase_recall(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KIRARI_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("GEMINI_EMBEDDING_ENABLED", "true")
    monkeypatch.setenv("GEMINI_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_EMBEDDING_DIMENSIONS", "128")
    monkeypatch.setenv("CODEX_MEMORY_RERANK", "false")

    import app.config as config
    import app.db as database
    import app.embeddings as embeddings
    import app.retrieval as retrieval

    importlib.reload(config)
    importlib.reload(database)
    importlib.reload(embeddings)
    importlib.reload(retrieval)
    database.init_db()
    database.upsert_memory_item(
        {
            "id": "mem_climbing",
            "type": "event",
            "title": "周六安排",
            "text": "每周六下午去城西的抱石馆攀岩。",
            "importance": 0.7,
        }
    )
    with database.db() as conn:
        assert conn.execute(
            "SELECT status FROM embedding_jobs WHERE memory_id='mem_climbing'"
        ).fetchone()[0] == "pending"

    async def fake_embedding(text, *, task_type, title=""):
        vector = [0.0] * 128
        vector[0] = 1.0
        return vector

    monkeypatch.setattr(embeddings, "generate_embedding", fake_embedding)
    assert asyncio.run(embeddings.process_embedding_queue(limit=10)) == 1
    results = asyncio.run(retrieval.recall_memories_with_codex("我周末做什么运动？"))
    assert results[0]["id"] == "mem_climbing"
    assert results[0]["_signals"]["mode"] == "gemini-vector-hybrid"
    assert results[0]["_signals"]["semantic"] == 1.0
    with database.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM embedding_jobs").fetchone()[0] == 0
        assert conn.execute("SELECT dimensions FROM memory_embeddings").fetchone()[0] == 128
