from __future__ import annotations

import json
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
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memory_items_fts USING fts5(
                id UNINDEXED,
                title,
                text,
                type UNINDEXED,
                content=''
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

            CREATE TABLE IF NOT EXISTS hermes_session_imports (
                source_path TEXT NOT NULL,
                line_no INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                imported_at REAL NOT NULL,
                PRIMARY KEY(source_path, line_no)
            );
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


def upsert_memory_item(item: dict[str, Any]) -> None:
    now = time.time()
    item = dict(item)
    item.setdefault("created_at", now)
    item.setdefault("updated_at", now)
    item.setdefault("importance", 0.5)
    item.setdefault("emotional_weight", 0.0)
    item.setdefault("resolved", 0)
    item.setdefault("approved", 1)
    item.setdefault("source_message_ids", [])
    with db() as conn:
        conn.execute(
            """
            INSERT INTO memory_items(
                id, type, title, text, source_message_ids, importance, emotional_weight,
                resolved, approved, embedding_json, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
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
                updated_at=excluded.updated_at
            """,
            (
                item["id"],
                item["type"],
                item.get("title", ""),
                item["text"],
                json.dumps(item.get("source_message_ids", []), ensure_ascii=False),
                float(item.get("importance", 0.5)),
                float(item.get("emotional_weight", 0.0)),
                int(item.get("resolved", 0)),
                int(item.get("approved", 1)),
                item.get("embedding_json"),
                float(item.get("created_at", now)),
                float(item.get("updated_at", now)),
            ),
        )
        conn.execute("DELETE FROM memory_items_fts WHERE id=?", (item["id"],))
        if int(item.get("approved", 1)):
            conn.execute(
                "INSERT INTO memory_items_fts(id, title, text, type) VALUES(?,?,?,?)",
                (item["id"], item.get("title", ""), item["text"], item["type"]),
            )
