from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import settings
from .db import db, log


def _sessions_dir() -> Path:
    return settings.hermes_home / "sessions"


def _load_session_index() -> dict[str, dict[str, Any]]:
    index_path = _sessions_dir() / "sessions.json"
    if not index_path.exists():
        return {}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    sessions: dict[str, dict[str, Any]] = {}
    for item in raw.values():
        if not isinstance(item, dict):
            continue
        session_id = str(item.get("session_id") or "").strip()
        if session_id:
            sessions[session_id] = item
    return sessions


def _telegram_origin(meta: dict[str, Any]) -> tuple[int, int] | None:
    origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
    platform = meta.get("platform") or origin.get("platform")
    if platform != "telegram":
        return None
    chat_id = origin.get("chat_id")
    user_id = origin.get("user_id")
    try:
        return int(chat_id), int(user_id)
    except (TypeError, ValueError):
        return None


def _record_ts(record: dict[str, Any], fallback: float) -> float:
    raw = record.get("timestamp")
    if not raw:
        return fallback
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    return ""


def _jsonl_files(index: dict[str, dict[str, Any]]) -> list[Path]:
    session_dir = _sessions_dir()
    paths: list[Path] = []
    for session_id, meta in index.items():
        if _telegram_origin(meta) is None:
            continue
        path = session_dir / f"{session_id}.jsonl"
        if path.exists():
            paths.append(path)
    if paths:
        return sorted(paths, key=lambda p: p.stat().st_mtime)
    return sorted(session_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def import_hermes_telegram_sessions(max_files: int | None = 50) -> dict[str, int]:
    """Import Telegram turns saved by Hermes Gateway into Kirari's local DB.

    Hermes Gateway is the preferred runtime for live chat. It writes sessions
    under ``~/.hermes/sessions``; Kirari mirrors those turns so dream/feel,
    review, and Mini App views can work from the same conversation history.
    """
    session_dir = _sessions_dir()
    if not session_dir.exists():
        return {"files": 0, "messages": 0, "skipped": 0}

    index = _load_session_index()
    files = _jsonl_files(index)
    if max_files is not None:
        files = files[-max_files:]

    imported = 0
    skipped = 0
    for path in files:
        session_id = path.stem
        origin = _telegram_origin(index.get(session_id, {}))
        if origin is None:
            skipped += 1
            continue
        chat_id, user_id = origin
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            skipped += 1
            continue

        fallback_ts = path.stat().st_mtime
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            role = record.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = _content_text(record.get("content"))
            if not text:
                continue
            direction = "in" if role == "user" else "out"
            created_at = _record_ts(record, fallback_ts)
            with db() as conn:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO hermes_session_imports(source_path, line_no, session_id, role, imported_at)
                    VALUES(?,?,?,?,?)
                    """,
                    (str(path), line_no, session_id, role, time.time()),
                )
                if cursor.rowcount == 0:
                    continue
                conn.execute(
                    """
                    INSERT INTO telegram_messages(
                        telegram_message_id, chat_id, user_id, direction, text, raw_json, created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        None,
                        chat_id,
                        user_id,
                        direction,
                        text,
                        json.dumps(
                            {
                                "source": "hermes_session",
                                "session_id": session_id,
                                "line_no": line_no,
                                "role": role,
                            },
                            ensure_ascii=False,
                        ),
                        created_at,
                    ),
                )
                imported += 1

    if imported:
        log("info", "imported Hermes Telegram session messages", {"messages": imported, "files": len(files)})
    return {"files": len(files), "messages": imported, "skipped": skipped}
