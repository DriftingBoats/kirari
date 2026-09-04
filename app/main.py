from __future__ import annotations

import json
import secrets
import time
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import ask_agent, runtime_status
from .companion import generate_companion_reply
from .config import settings
from .db import db, init_db, row_to_dict, rows_to_dicts
from .dream import dream_loop, run_dream
from .embeddings import (
    embedding_status,
    embedding_worker_loop,
    process_embedding_queue,
    reconcile_embedding_jobs,
)
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
from .proactive import proactive_loop, run_proactive_once
from .reminders import reminder_loop, snooze
from .retrieval import (
    conversation_is_cold,
    recent_telegram_context,
    recall_memories_with_codex,
    render_recalled,
    surface_memories,
)
from .memory_store import find_bucket_paths, persist_bucket, reconcile_memory_store
from .memory_service import (
    get_memory,
    reinforce_memory as reinforce_memory_record,
    restore_memory as restore_memory_record,
    save_memory_candidate,
    tombstone_memory,
)
from .memory_lifecycle import memory_decay_loop, memory_lifecycle_status, run_memory_decay
from .schemas import BoardCreate, CalendarCreate, ChatRequest, FileUpdate, ReminderCreate, ReviewAction
from .telegram import save_telegram_message, send_message, telegram_polling_loop, telegram_webhook
from .telegram_webapp import TelegramWebAppAuthError, validate_init_data

_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_memory_files()
    await asyncio.to_thread(reconcile_memory_store)
    global _background_tasks
    _background_tasks = [
        asyncio.create_task(reminder_loop(send_message)),
        asyncio.create_task(dream_loop()),
        asyncio.create_task(proactive_loop(send_message)),
        asyncio.create_task(memory_decay_loop()),
        asyncio.create_task(embedding_worker_loop()),
    ]
    if settings.telegram_bot_token and settings.telegram_mode == "polling":
        _background_tasks.append(asyncio.create_task(telegram_polling_loop()))
    yield
    for task in _background_tasks:
        task.cancel()
    await asyncio.gather(*_background_tasks, return_exceptions=True)


app = FastAPI(title="Kirari Companion", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent.parent / "static")), name="static")


def _request_key(request: Request) -> str:
    return (
        request.headers.get("x-kirari-key")
        or request.query_params.get("key")
        or request.cookies.get("kirari_key")
        or ""
    )


def _telegram_init_data(request: Request) -> str:
    return request.headers.get("x-telegram-init-data") or request.query_params.get("tg_init_data") or ""


def _valid_access_key(request: Request) -> bool:
    return bool(settings.access_key) and secrets.compare_digest(_request_key(request), settings.access_key)


def _valid_telegram_webapp(request: Request) -> bool:
    if not settings.telegram_bot_token:
        return False
    try:
        validate_init_data(
            _telegram_init_data(request),
            bot_token=settings.telegram_bot_token,
            allowed_user_ids=settings.telegram_allowed_user_ids,
            max_age_seconds=settings.telegram_webapp_auth_max_age_seconds,
        )
    except TelegramWebAppAuthError:
        return False
    return True


@app.middleware("http")
async def require_access_key(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/auth/status":
        auth_required = bool(settings.access_key or settings.telegram_bot_token)
        if auth_required and not (_valid_access_key(request) or _valid_telegram_webapp(request)):
            return JSONResponse({"detail": "invalid access key"}, status_code=401)
    return await call_next(request)


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.get("/api/auth/status")
async def auth_status():
    return {
        "required": bool(settings.access_key or settings.telegram_bot_token),
        "telegram_configured": bool(settings.telegram_bot_token),
        "telegram_user_restricted": bool(settings.telegram_allowed_user_ids),
    }


@app.get("/api/status")
async def status():
    return {
        "runtime": await asyncio.to_thread(runtime_status),
        "memory_index": embedding_status(),
        "memory_lifecycle": memory_lifecycle_status(),
        "memory_dir": str(settings.memory_dir),
        "telegram_configured": bool(settings.telegram_bot_token),
        "telegram_mode": settings.telegram_mode,
        "db_path": str(settings.db_path),
        "proactive": {
            "enabled": settings.proactive_enabled,
            "idle_hours": settings.proactive_idle_hours,
            "cooldown_hours": settings.proactive_cooldown_hours,
            "quiet_hours": [settings.proactive_quiet_start, settings.proactive_quiet_end],
        },
        "scheduled_dream": {"enabled": settings.dream_schedule_enabled, "hour": settings.dream_hour},
        "timezone": settings.app_timezone,
    }


@app.post("/telegram/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    return await telegram_webhook(request, x_telegram_bot_api_secret_token)


@app.post("/api/chat/test")
async def test_chat(body: ChatRequest):
    recalled_items = await recall_memories_with_codex(body.text)
    recalled = render_recalled(recalled_items)
    recent = recent_telegram_context(body.chat_id, settings.recent_message_limit) if body.chat_id else ""
    result = await ask_agent(body.text, recent_context=recent, recalled_context=recalled)
    return {"ok": result.ok, "text": result.text, "stderr": result.stderr, "returncode": result.returncode}


@app.post("/api/chat")
async def local_chat(body: ChatRequest):
    chat_id = body.chat_id or -1
    cold_start = conversation_is_cold(chat_id)
    incoming_id = save_telegram_message(
        telegram_message_id=None,
        chat_id=chat_id,
        user_id=0,
        direction="in",
        text=body.text,
        raw={"source": "web"},
    )
    recalled_items = await recall_memories_with_codex(body.text)
    if cold_start:
        recalled_ids = {str(item["id"]) for item in recalled_items}
        recalled_items.extend(
            item for item in surface_memories()
            if str(item["id"]) not in recalled_ids
        )
    recalled = render_recalled(recalled_items)
    recent = recent_telegram_context(
        chat_id, settings.recent_message_limit, exclude_row_id=incoming_id
    )
    result = await generate_companion_reply(
        body.text,
        recent_context=recent,
        recalled_context=recalled,
        recalled_items=recalled_items,
        source_message_ids=[incoming_id],
    )
    save_telegram_message(
        telegram_message_id=None,
        chat_id=chat_id,
        user_id=0,
        direction="out",
        text=result.text,
        raw={
            "source": "web",
            "codex_ok": result.ok,
            "review_ids": result.data.get("review_ids", []),
            "reinforced_memory_ids": result.data.get("reinforced_memory_ids", []),
        },
    )
    return {"ok": result.ok, "text": result.text, "review_ids": result.data.get("review_ids", [])}


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
    return {"ok": True, "context_refreshed": True}


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
    return {"ok": True, "context_refreshed": True}


@app.get("/api/messages")
async def messages(limit: int = 100, chat_id: int | None = None):
    with db() as conn:
        if chat_id is None:
            rows = conn.execute(
                "SELECT * FROM telegram_messages ORDER BY created_at DESC LIMIT ?",
                (min(limit, 500),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM telegram_messages WHERE chat_id=? ORDER BY created_at DESC LIMIT ?",
                (chat_id, min(limit, 500)),
            ).fetchall()
    return list(reversed(rows_to_dicts(rows)))


@app.get("/api/memories")
async def memories(
    q: str = "",
    limit: int = 100,
    domain: str = "",
    tags: str = "",
    date_from: float | None = None,
    date_to: float | None = None,
    importance_min: float = 0.0,
    include_archived: bool = True,
):
    if q:
        return await recall_memories_with_codex(
            q,
            limit=min(limit, 50),
            include_archived=include_archived,
            domain=domain,
            tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
            date_from=date_from,
            date_to=date_to,
            importance_min=max(0.0, min(1.0, importance_min)),
        )
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memory_items WHERE tombstoned=0
            ORDER BY archived ASC, pinned DESC, importance DESC, updated_at DESC LIMIT ?
            """,
            (min(limit, 500),),
        ).fetchall()
    return rows_to_dicts(rows)


@app.get("/api/memories/feel/search")
async def search_feelings(q: str, limit: int = 20):
    return await recall_memories_with_codex(
        q,
        limit=min(max(limit, 1), 50),
        include_archived=True,
        include_special=True,
        memory_type="feel",
    )


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
        "valence": float(body.get("valence", 0.5)),
        "arousal": float(body.get("arousal", body.get("emotional_weight", 0.3))),
        "pinned": int(body.get("pinned", body.get("type") == "pinned")),
        "summary": str(body.get("summary", "")),
        "domains": body.get("domains", []),
        "tags": body.get("tags", []),
        "entities": body.get("entities", []),
        "why_remembered": str(body.get("why_remembered", "")),
        "approved": int(body.get("approved", 1)),
        "resolved": int(body.get("resolved", 0)),
        "created_at": now,
        "updated_at": now,
        "embedding_json": None,
    }
    saved = await save_memory_candidate(
        item,
        source_message_ids=[int(value) for value in body.get("source_message_ids", [])],
        allow_merge=bool(body.get("allow_merge", True)),
    )
    return {
        "ok": True,
        "id": saved["item"]["id"],
        "created": saved["created"],
        "merged_into": saved["merged_into"],
        "context_refreshed": True,
    }


@app.patch("/api/memories/{memory_id}")
async def update_memory(memory_id: str, body: dict):
    allowed = {
        "title", "text", "importance", "emotional_weight", "valence", "arousal",
        "resolved", "approved", "pinned", "archived", "summary", "domains_json",
        "tags_json", "entities_json", "why_remembered",
    }
    updates = {key: value for key, value in body.items() if key in allowed}
    if not updates:
        return {"ok": True}
    item = get_memory(memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    item.update(updates)
    item["embedding_json"] = None
    await asyncio.to_thread(persist_bucket, item, "edited")
    return {"ok": True}


@app.post("/api/memories/{memory_id}/reinforce")
async def reinforce_memory(memory_id: str):
    """Explicitly reinforce a memory after it proved useful.

    Retrieval itself intentionally stays read-only.
    """
    reinforced = await asyncio.to_thread(reinforce_memory_record, memory_id)
    if not reinforced:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "reinforced": True}


@app.post("/api/memories/{memory_id}/restore")
async def restore_memory(memory_id: str):
    restored = await asyncio.to_thread(restore_memory_record, memory_id)
    if not restored:
        raise HTTPException(status_code=404, detail="not found or tombstoned")
    return {"ok": True, "restored": True}


@app.get("/api/memories/{memory_id}/trace")
async def trace_memory(memory_id: str):
    item = get_memory(memory_id)
    if not item:
        raise HTTPException(status_code=404, detail="not found")
    try:
        source_ids = [int(value) for value in json.loads(item.get("source_message_ids") or "[]")]
    except (TypeError, ValueError, json.JSONDecodeError):
        source_ids = []
    source_messages: list[dict] = []
    if source_ids:
        placeholders = ",".join("?" for _ in source_ids)
        with db() as conn:
            source_messages = rows_to_dicts(
                conn.execute(
                    f"SELECT id, direction, text, created_at FROM telegram_messages WHERE id IN ({placeholders}) ORDER BY created_at",
                    source_ids,
                ).fetchall()
            )
    paths = find_bucket_paths(memory_id)
    return {
        "memory": item,
        "source_messages": source_messages,
        "footprints": json.loads(item.get("footprints_json") or "[]"),
        "lineage": json.loads(item.get("lineage_json") or "{}"),
        "bucket_path": str(paths[0]) if paths else "",
    }


@app.get("/api/memories/surface")
async def surface_memory(limit: int = 3):
    return await asyncio.to_thread(surface_memories, min(max(limit, 1), 20))


@app.post("/api/memories/decay")
async def memory_decay(body: dict):
    return await asyncio.to_thread(run_memory_decay, apply=bool(body.get("apply", False)))


@app.post("/api/memory-index/reindex")
async def reindex_memories(body: dict):
    queued = await asyncio.to_thread(
        reconcile_embedding_jobs, force=bool(body.get("force", False))
    )
    processed = 0
    if bool(body.get("wait", False)):
        processed = await process_embedding_queue(limit=min(int(body.get("limit", 100)), 500))
    return {"ok": True, "queued": queued, "processed": processed, "index": embedding_status()}


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: str):
    deleted = await asyncio.to_thread(tombstone_memory, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "tombstoned": True, "recoverable": True}


@app.post("/api/messages/{message_id}/pin")
async def pin_message(message_id: int, body: dict):
    target = str(body.get("target", "memory")).lower()
    if target not in {"memory", "pinned"}:
        raise HTTPException(status_code=400, detail="invalid target")
    with db() as conn:
        row = conn.execute("SELECT text FROM telegram_messages WHERE id=?", (message_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="message not found")
    text = str(row["text"]).strip()
    heading = str(body.get("title") or f"Pinned message {message_id}")
    if target == "pinned":
        append_memory_file("PINNED.md", heading, text)
    created = await create_memory(
        {
            "type": "pinned",
            "title": heading,
            "text": text,
            "importance": 1.0,
            "pinned": 1,
            "source_message_ids": [message_id],
            "allow_merge": False,
        }
    )
    return {"ok": True, "target": "bucket", "id": created["id"]}


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
    return {"ok": True, "id": item_id, "context_refreshed": True}


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
    if "snooze_seconds" in body:
        if not snooze(item_id, int(body["snooze_seconds"])):
            raise HTTPException(status_code=404, detail="not found")
        return {"ok": True, "snoozed": True}
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
        await save_memory_candidate(
            {
                "type": "feel", "title": heading, "text": text,
                "importance": payload.get("importance", 0.7),
                "valence": payload.get("valence", 0.5),
                "arousal": payload.get("arousal", 0.5),
                "summary": payload.get("summary", ""),
                "domains": payload.get("domains", ["relationship"]),
                "tags": payload.get("tags", ["feel"]),
                "entities": payload.get("entities", []),
                "why_remembered": payload.get("why_remembered", ""),
            },
            source_message_ids=payload.get("source_message_ids", []),
            allow_merge=False,
        )
        return
    if kind in {"promise", "boundary"}:
        append_memory_file("PINNED.md", f"Reviewed {heading}", text)
        await save_memory_candidate(
            {
                "type": kind, "title": heading, "text": text,
                "importance": 1.0, "pinned": 1,
                "summary": payload.get("summary", ""),
                "domains": payload.get("domains", ["relationship"]),
                "tags": payload.get("tags", [kind]),
                "entities": payload.get("entities", []),
                "why_remembered": payload.get("why_remembered", "user approved"),
            },
            source_message_ids=payload.get("source_message_ids", []),
            allow_merge=False,
        )
        return
    if kind in {"reminder", "calendar"}:
        raw_when = str(payload.get("when", "")).strip()
        try:
            when = datetime.fromisoformat(raw_when.replace("Z", "+00:00"))
            if when.tzinfo is None:
                try:
                    when = when.replace(tzinfo=ZoneInfo(settings.app_timezone))
                except ZoneInfoNotFoundError:
                    when = when.astimezone()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="review item has invalid time") from exc
        if kind == "reminder":
            await create_reminder(
                ReminderCreate(
                    title=heading,
                    description=text,
                    remind_at=when.timestamp(),
                    repeat_rule=str(payload.get("repeat_rule", "")),
                    source="chat-review",
                )
            )
        else:
            await create_calendar(
                CalendarCreate(
                    layer=str(payload.get("layer") or "life"),
                    title=heading,
                    description=text,
                    starts_at=when.timestamp(),
                    source="chat-review",
                    confirmed=True,
                )
            )
        return
    await create_memory(
        {
            "type": payload.get("type") or payload.get("kind") or "event",
            "title": payload.get("title") or payload.get("kind") or "reviewed",
            "text": text,
            "importance": payload.get("importance", 0.6),
            "emotional_weight": payload.get("arousal", 0.3),
            "valence": payload.get("valence", 0.5),
            "arousal": payload.get("arousal", 0.3),
            "summary": payload.get("summary", ""),
            "domains": payload.get("domains", []),
            "tags": payload.get("tags", []),
            "entities": payload.get("entities", []),
            "why_remembered": payload.get("why_remembered", ""),
            "source_message_ids": payload.get("source_message_ids", []),
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
    if body.action == "approve":
        await _approve_review(row)
    status = "approved" if body.action == "approve" else "rejected"
    with db() as conn:
        conn.execute("UPDATE pending_reviews SET status=?, updated_at=? WHERE id=?", (status, time.time(), review_id))
    return {"ok": True}


@app.post("/api/dream/run")
async def dream_run():
    return await run_dream("manual")


@app.post("/api/proactive/run")
async def proactive_run():
    return await run_proactive_once(send_message)


@app.get("/api/logs")
async def logs():
    with db() as conn:
        rows = conn.execute("SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 200").fetchall()
    return rows_to_dicts(rows)
