from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .config import settings


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterable[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    settings.app_data_dir.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_message_id INTEGER,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('in','out')),
                text TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_items (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                source_message_ids TEXT NOT NULL DEFAULT '[]',
                importance REAL NOT NULL DEFAULT 0.5,
                emotional_weight REAL NOT NULL DEFAULT 0.0,
                resolved INTEGER NOT NULL DEFAULT 0,
                approved INTEGER NOT NULL DEFAULT 1,
                embedding_json TEXT,
                valence REAL NOT NULL DEFAULT 0.5,
                arousal REAL NOT NULL DEFAULT 0.3,
                activation_count REAL NOT NULL DEFAULT 0,
                last_active REAL,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                summary TEXT NOT NULL DEFAULT '',
                domains_json TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                entities_json TEXT NOT NULL DEFAULT '[]',
                why_remembered TEXT NOT NULL DEFAULT '',
                digested INTEGER NOT NULL DEFAULT 0,
                tombstoned INTEGER NOT NULL DEFAULT 0,
                archived_at REAL,
                deleted_at REAL,
                footprints_json TEXT NOT NULL DEFAULT '[]',
                lineage_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
                id UNINDEXED,
                title,
                text,
                metadata_text,
                type UNINDEXED
            );

            CREATE TABLE IF NOT EXISTS memory_embeddings (
                memory_id TEXT PRIMARY KEY REFERENCES memory_items(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS embedding_jobs (
                memory_id TEXT PRIMARY KEY REFERENCES memory_items(id) ON DELETE CASCADE,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at REAL NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS board_messages (
                id TEXT PRIMARY KEY,
                author TEXT NOT NULL CHECK(author IN ('user','ai')),
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                unread INTEGER NOT NULL DEFAULT 1,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                pushed_at REAL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                layer TEXT NOT NULL CHECK(layer IN ('life','relationship','work')),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                starts_at REAL NOT NULL,
                ends_at REAL,
                source TEXT NOT NULL DEFAULT 'manual',
                confirmed INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                remind_at REAL NOT NULL,
                repeat_rule TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                sent_at REAL
            );

            CREATE TABLE IF NOT EXISTS pending_reviews (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dream_runs (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                feel TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                data_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            );
            """
        )
        _ensure_column(conn, "memory_items", "valence", "REAL NOT NULL DEFAULT 0.5")
        _ensure_column(conn, "memory_items", "arousal", "REAL NOT NULL DEFAULT 0.3")
        _ensure_column(conn, "memory_items", "activation_count", "REAL NOT NULL DEFAULT 0")
        _ensure_column(conn, "memory_items", "last_active", "REAL")
        _ensure_column(conn, "memory_items", "pinned", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "memory_items", "archived", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "memory_items", "summary", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "memory_items", "domains_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "memory_items", "tags_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "memory_items", "entities_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "memory_items", "why_remembered", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "memory_items", "digested", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "memory_items", "tombstoned", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "memory_items", "archived_at", "REAL")
        _ensure_column(conn, "memory_items", "deleted_at", "REAL")
        _ensure_column(conn, "memory_items", "footprints_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "memory_items", "lineage_json", "TEXT NOT NULL DEFAULT '{}'")
        # Telegram retries webhooks. Keep one inbound copy so a retry cannot
        # trigger duplicate companion replies or duplicate memory extraction.
        conn.execute(
            """
            DELETE FROM telegram_messages
            WHERE direction='in' AND telegram_message_id IS NOT NULL
              AND id NOT IN (
                SELECT MIN(id) FROM telegram_messages
                WHERE direction='in' AND telegram_message_id IS NOT NULL
                GROUP BY chat_id, telegram_message_id
              )
            """
        )
        fts_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_items_fts'"
        ).fetchone()
        fts_definition = str(fts_sql["sql"] or "") if fts_sql else ""
        if fts_sql and (
            "content=''" in fts_definition.replace(" ", "")
            or "metadata_text" not in fts_definition
        ):
            conn.execute("DROP TABLE memory_items_fts")
            conn.execute(
                """
                CREATE VIRTUAL TABLE memory_items_fts USING fts5(
                    id UNINDEXED, title, text, metadata_text, type UNINDEXED
                )
                """
            )
        conn.execute("DELETE FROM memory_items_fts")
        conn.execute(
            """
            INSERT INTO memory_items_fts(id, title, text, metadata_text, type)
            SELECT id, title, text,
                   summary || ' ' || domains_json || ' ' || tags_json || ' ' || entities_json,
                   type FROM memory_items
            WHERE approved=1 AND resolved=0 AND archived=0 AND tombstoned=0
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS telegram_inbound_unique
            ON telegram_messages(chat_id, telegram_message_id)
            WHERE direction='in' AND telegram_message_id IS NOT NULL
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(r) or {} for r in rows]


def log(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO system_logs(level, message, data_json, created_at) VALUES(?,?,?,?)",
            (level, message, json.dumps(data or {}, ensure_ascii=False), time.time()),
        )


def memory_embedding_document(item: dict[str, Any]) -> str:
    """Build the canonical text indexed by the embedding projection."""
    parts = [
        str(item.get("title", "")).strip(),
        str(item.get("summary", "")).strip(),
        str(item.get("text", "")).strip(),
        str(item.get("domains_json", item.get("domains", []))).strip(),
        str(item.get("tags_json", item.get("tags", []))).strip(),
        str(item.get("entities_json", item.get("entities", []))).strip(),
        str(item.get("why_remembered", "")).strip(),
    ]
    return "\n".join(part for part in parts if part)


def memory_embedding_hash(item: dict[str, Any]) -> str:
    return hashlib.sha256(memory_embedding_document(item).encode("utf-8")).hexdigest()


def upsert_memory_item(item: dict[str, Any]) -> None:
    now = time.time()
    item = dict(item)
    item.setdefault("created_at", now)
    item.setdefault("updated_at", now)
    item.setdefault("importance", 0.5)
    item.setdefault("emotional_weight", 0.0)
    item.setdefault("resolved", 0)
    item.setdefault("approved", 1)
    item.setdefault("valence", 0.5)
    item.setdefault("arousal", item.get("emotional_weight", 0.3))
    item.setdefault("activation_count", 0)
    item.setdefault("last_active", item.get("created_at", now))
    item.setdefault("pinned", 1 if item.get("type") == "pinned" else 0)
    item.setdefault("archived", 0)
    item.setdefault("summary", "")
    item.setdefault("domains_json", item.get("domains", []))
    item.setdefault("tags_json", item.get("tags", []))
    item.setdefault("entities_json", item.get("entities", []))
    item.setdefault("why_remembered", "")
    item.setdefault("digested", 0)
    item.setdefault("tombstoned", 0)
    item.setdefault("archived_at", None)
    item.setdefault("deleted_at", None)
    item.setdefault("footprints_json", item.get("footprints", []))
    item.setdefault("lineage_json", item.get("lineage", {}))
    item.setdefault("source_message_ids", [])
    source_message_ids = item.get("source_message_ids", [])
    if not isinstance(source_message_ids, str):
        source_message_ids = json.dumps(source_message_ids, ensure_ascii=False)
    structured_fields: dict[str, str] = {}
    for key in ("domains_json", "tags_json", "entities_json", "footprints_json", "lineage_json"):
        value = item.get(key, [])
        structured_fields[key] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        item[key] = structured_fields[key]
    with db() as conn:
        conn.execute(
            """
            INSERT INTO memory_items(
                id, type, title, text, source_message_ids, importance, emotional_weight,
                resolved, approved, embedding_json, valence, arousal, activation_count,
                last_active, pinned, archived, summary, domains_json, tags_json,
                entities_json, why_remembered, digested, tombstoned, archived_at,
                deleted_at, footprints_json, lineage_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type,
                title=excluded.title,
                text=excluded.text,
                source_message_ids=excluded.source_message_ids,
                importance=excluded.importance,
                emotional_weight=excluded.emotional_weight,
                resolved=excluded.resolved,
                approved=excluded.approved,
                embedding_json=excluded.embedding_json,
                valence=excluded.valence,
                arousal=excluded.arousal,
                activation_count=excluded.activation_count,
                last_active=excluded.last_active,
                pinned=excluded.pinned,
                archived=excluded.archived,
                summary=excluded.summary,
                domains_json=excluded.domains_json,
                tags_json=excluded.tags_json,
                entities_json=excluded.entities_json,
                why_remembered=excluded.why_remembered,
                digested=excluded.digested,
                tombstoned=excluded.tombstoned,
                archived_at=excluded.archived_at,
                deleted_at=excluded.deleted_at,
                footprints_json=excluded.footprints_json,
                lineage_json=excluded.lineage_json,
                updated_at=excluded.updated_at
            """,
            (
                item["id"],
                item["type"],
                item.get("title", ""),
                item["text"],
                source_message_ids,
                float(item.get("importance", 0.5)),
                float(item.get("emotional_weight", 0.0)),
                int(item.get("resolved", 0)),
                int(item.get("approved", 1)),
                item.get("embedding_json"),
                float(item.get("valence", 0.5)),
                float(item.get("arousal", 0.3)),
                float(item.get("activation_count", 0)),
                float(item.get("last_active") or now),
                int(item.get("pinned", 0)),
                int(item.get("archived", 0)),
                str(item.get("summary", "")),
                structured_fields["domains_json"],
                structured_fields["tags_json"],
                structured_fields["entities_json"],
                str(item.get("why_remembered", "")),
                int(item.get("digested", 0)),
                int(item.get("tombstoned", 0)),
                item.get("archived_at"),
                item.get("deleted_at"),
                structured_fields["footprints_json"],
                structured_fields["lineage_json"],
                float(item.get("created_at", now)),
                float(item.get("updated_at", now)),
            ),
        )
        conn.execute("DELETE FROM memory_items_fts WHERE id=?", (item["id"],))
        if (
            int(item.get("approved", 1))
            and not int(item.get("resolved", 0))
            and not int(item.get("archived", 0))
            and not int(item.get("tombstoned", 0))
        ):
            conn.execute(
                """
                INSERT INTO memory_items_fts(id, title, text, metadata_text, type)
                VALUES(?,?,?,?,?)
                """,
                (
                    item["id"],
                    item.get("title", ""),
                    item["text"],
                    " ".join(
                        [
                            str(item.get("summary", "")),
                            structured_fields["domains_json"],
                            structured_fields["tags_json"],
                            structured_fields["entities_json"],
                        ]
                    ),
                    item["type"],
                ),
            )
        if (
            settings.gemini_embedding_enabled
            and int(item.get("approved", 1))
            and not int(item.get("tombstoned", 0))
        ):
            content_hash = memory_embedding_hash(item)
            current = conn.execute(
                "SELECT content_hash FROM memory_embeddings WHERE memory_id=?",
                (item["id"],),
            ).fetchone()
            if current is None or str(current["content_hash"]) != content_hash:
                conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (item["id"],))
                conn.execute(
                    """
                    INSERT INTO embedding_jobs(
                        memory_id, content_hash, status, attempts, next_attempt_at,
                        last_error, created_at, updated_at
                    ) VALUES(?,?, 'pending', 0, 0, '', ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        status='pending', attempts=0, next_attempt_at=0,
                        last_error='', updated_at=excluded.updated_at
                    """,
                    (item["id"], content_hash, now, now),
                )
        else:
            conn.execute("DELETE FROM embedding_jobs WHERE memory_id=?", (item["id"],))
            if int(item.get("tombstoned", 0)):
                conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (item["id"],))
