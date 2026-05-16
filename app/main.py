from __future__ import annotations

import json
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import db, init_db, row_to_dict, rows_to_dicts, upsert_memory_item
from .dream import run_dream
from .hermes_client import ask_hermes, hermes_available
from .hermes_sessions import import_hermes_telegram_sessions
from .memory_files import (
    MEMORY_FILES,
    append_memory_file,
    ensure_memory_files,
    list_file_versions,
    memory_file_path,
    read_memory_file,
    restore_file_version,
    write_memory_file,
)
from .reminders import reminder_loop
from .retrieval import recent_telegram_context, recall_memories, render_recalled, simple_embedding
from .schemas import BoardCreate, CalendarCreate, ChatRequest, FileUpdate, ReminderCreate, ReviewAction
from .telegram import send_message, telegram_webhook

_reminder_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_memory_files()
    global _reminder_task
    import asyncio

    _reminder_task = asyncio.create_task(reminder_loop(send_message))
    yield
    if _reminder_task:
        _reminder_task.cancel()


app = FastAPI(title="Aion Hermes Telegram", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")


def _request_key(request: Request) -> str:
    return (
        request.headers.get("x-kirari-key")
        or request.query_params.get("key")
        or request.cookies.get("kirari_key")
        or ""
    )


@app.middleware("http")
async def require_access_key(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/auth/status":
        if settings.access_key and not secrets.compare_digest(_request_key(request), settings.access_key):
            return JSONResponse({"detail": "invalid access key"}, status_code=401)
    return await call_next(request)


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.get("/api/auth/status")
async def auth_status():
    return {"required": bool(settings.access_key)}


@app.get("/api/status")
async def status():
    return {
        "hermes_available": hermes_available(),
        "hermes_bin": settings.hermes_bin,
        "hermes_home": str(settings.hermes_home),
        "hermes_sessions_dir": str(settings.hermes_home / "sessions"),
        "memory_dir": str(settings.memory_dir),
        "telegram_configured": bool(settings.telegram_bot_token),
        "db_path": str(settings.db_path),
    }


@app.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    return await telegram_webhook(request, x_telegram_bot_api_secret_token)


@app.post("/api/chat/test")
async def test_chat(body: ChatRequest):
    recalled = render_recalled(recall_memories(body.text))
    recent = recent_telegram_context(body.chat_id, settings.recent_message_limit) if body.chat_id else ""
    result = await ask_hermes(body.text, recent_context=recent, recalled_context=recalled)
    return {"ok": result.ok, "text": result.text, "stderr": result.stderr, "returncode": result.returncode}


@app.get("/api/files")
async def list_files():
    ensure_memory_files()
    return [
        {"name": name, "size": len(read_memory_file(name)), "path": str(memory_file_path(name))}
        for name in MEMORY_FILES.keys()
    ]


@app.get("/api/files/{filename}")
async def get_file(filename: str):
    try:
        return {"name": filename, "content": read_memory_file(filename)}
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown file")


@app.put("/api/files/{filename}")
async def put_file(filename: str, body: FileUpdate):
    try:
        write_memory_file(filename, body.content)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown file")
    return {"ok": True}


@app.get("/api/files/{filename}/versions")
async def file_versions(filename: str, limit: int = 20):
    try:
        return list_file_versions(filename, limit)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown file")


@app.post("/api/files/{filename}/versions/{version_id}/restore")
async def restore_file(filename: str, version_id: int):
    try:
        restore_file_version(filename, version_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="unknown file version")
    return {"ok": True}


@app.get("/api/messages")
async def messages(limit: int = 100):
    import_hermes_telegram_sessions()
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM telegram_messages ORDER BY created_at DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
    return list(reversed(rows_to_dicts(rows)))


@app.post("/api/import/hermes-sessions")
async def import_hermes_sessions():
    return {"ok": True, **import_hermes_telegram_sessions()}


@app.get("/api/memories")
async def memories(q: str = "", limit: int = 100):
    if q:
        return recall_memories(q, limit=min(limit, 50))
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM memory_items ORDER BY importance DESC, updated_at DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/memories")
async def create_memory(body: dict):
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    now = time.time()
    mem_id = body.get("id") or f"mem_{uuid.uuid4().hex}"
    item = {
        "id": mem_id,
        "type": body.get("type", "fact"),
        "title": body.get("title", ""),
        "text": text,
        "importance": float(body.get("importance", 0.5)),
        "emotional_weight": float(body.get("emotional_weight", 0.0)),
        "approved": int(body.get("approved", 1)),
        "resolved": int(body.get("resolved", 0)),
        "created_at": now,
        "updated_at": now,
        "embedding_json": json.dumps(simple_embedding(text), ensure_ascii=False),
    }
    upsert_memory_item(item)
    append_memory_file("MEMORY.md", item["title"] or item["type"], text)
    return {"ok": True, "id": mem_id}


@app.get("/api/board")
async def board():
    with db() as conn:
        rows = conn.execute("SELECT * FROM board_messages ORDER BY created_at DESC LIMIT 200").fetchall()
    return rows_to_dicts(rows)


@app.post("/api/board")
async def create_board(body: BoardCreate):
    if body.author not in {"user", "ai"}:
        raise HTTPException(status_code=400, detail="invalid author")
    now = time.time()
    item_id = f"board_{uuid.uuid4().hex}"
    with db() as conn:
        conn.execute(
            "INSERT INTO board_messages(id, author, text, source, unread, created_at) VALUES(?,?,?,?,?,?)",
            (item_id, body.author, body.text, body.source, 1, now),
        )
    append_memory_file("BOARD.md", f"{body.author} {time.strftime('%Y-%m-%d')}", body.text)
    return {"ok": True, "id": item_id}


@app.patch("/api/board/{item_id}")
async def update_board(item_id: str, body: dict):
    allowed = {"unread", "pinned", "archived"}
    sets, vals = [], []
    for key in allowed:
        if key in body:
            sets.append(f"{key}=?")
            vals.append(1 if body[key] else 0)
    if not sets:
        return {"ok": True}
    vals.append(item_id)
    with db() as conn:
        conn.execute(f"UPDATE board_messages SET {', '.join(sets)} WHERE id=?", vals)
    return {"ok": True}


@app.get("/api/calendar")
async def calendar():
    with db() as conn:
        rows = conn.execute("SELECT * FROM calendar_events ORDER BY starts_at ASC LIMIT 500").fetchall()
    return rows_to_dicts(rows)


@app.post("/api/calendar")
async def create_calendar(body: CalendarCreate):
    if body.layer not in {"life", "relationship", "work"}:
        raise HTTPException(status_code=400, detail="invalid layer")
    now = time.time()
    item_id = f"cal_{uuid.uuid4().hex}"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO calendar_events(id, layer, title, description, starts_at, ends_at, source, confirmed, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item_id,
                body.layer,
                body.title,
                body.description,
                body.starts_at,
                body.ends_at,
                body.source,
                1 if body.confirmed else 0,
                now,
                now,
            ),
        )
    return {"ok": True, "id": item_id}


@app.get("/api/reminders")
async def reminders():
    with db() as conn:
        rows = conn.execute("SELECT * FROM reminders ORDER BY remind_at ASC LIMIT 500").fetchall()
    return rows_to_dicts(rows)


@app.post("/api/reminders")
async def create_reminder(body: ReminderCreate):
    now = time.time()
    item_id = f"rem_{uuid.uuid4().hex}"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO reminders(id, title, description, remind_at, repeat_rule, status, source, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (item_id, body.title, body.description, body.remind_at, body.repeat_rule, "pending", body.source, now, now),
        )
    return {"ok": True, "id": item_id}


@app.patch("/api/reminders/{item_id}")
async def update_reminder(item_id: str, body: dict):
    status = body.get("status")
    if status not in {"pending", "done", "sent", "cancelled"}:
        raise HTTPException(status_code=400, detail="invalid status")
    with db() as conn:
        conn.execute("UPDATE reminders SET status=?, updated_at=? WHERE id=?", (status, time.time(), item_id))
    return {"ok": True}


@app.get("/api/reviews")
async def reviews():
    with db() as conn:
        rows = conn.execute("SELECT * FROM pending_reviews ORDER BY created_at DESC LIMIT 200").fetchall()
    result = []
    for row in rows_to_dicts(rows):
        row["payload"] = json.loads(row.pop("payload_json") or "{}")
        result.append(row)
    return result


async def _approve_review(row) -> None:
    payload = json.loads(row["payload_json"] or "{}")
    text = str(payload.get("text", "")).strip()
    if not text:
        return
    kind = str(row["kind"] or payload.get("kind") or "memory").strip().lower()
    heading = str(payload.get("title") or payload.get("kind") or kind).strip().title()
    if kind == "feel":
        append_memory_file("FEEL.md", f"Reviewed {heading}", text)
        return
    if kind in {"promise", "boundary"}:
        append_memory_file("PINNED.md", f"Reviewed {heading}", text)
        return
    await create_memory(
        {
            "type": payload.get("type") or payload.get("kind") or "event",
            "title": payload.get("title") or payload.get("kind") or "reviewed",
            "text": text,
            "importance": payload.get("importance", 0.6),
            "emotional_weight": payload.get("emotional_weight", 0.0),
        }
    )


@app.post("/api/reviews/{review_id}")
async def review_action(review_id: str, body: ReviewAction):
    if body.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="invalid action")
    with db() as conn:
        row = conn.execute("SELECT * FROM pending_reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        status = "approved" if body.action == "approve" else "rejected"
        conn.execute("UPDATE pending_reviews SET status=?, updated_at=? WHERE id=?", (status, time.time(), review_id))
    if body.action == "approve":
        await _approve_review(row)
    return {"ok": True}


@app.post("/api/dream/run")
async def dream_run():
    return await run_dream("manual")


@app.get("/api/logs")
async def logs():
    with db() as conn:
        rows = conn.execute("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    return rows_to_dicts(rows)
