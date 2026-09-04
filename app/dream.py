from __future__ import annotations

import json
import asyncio
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent import ask_agent_json
from .config import settings
from .db import db, log
from .memory_files import append_memory_file, file_bundle
from .memory_service import propose_feel_crystallization, save_memory_candidate


DREAM_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "feel": {"type": "string"},
        "feel_valence": {"type": "number", "minimum": 0, "maximum": 1},
        "feel_arousal": {"type": "number", "minimum": 0, "maximum": 1},
        "low_risk_memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["fact", "event", "pattern"]},
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "importance": {"type": "number", "minimum": 0, "maximum": 1},
                    "emotional_weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "valence": {"type": "number", "minimum": 0, "maximum": 1},
                    "arousal": {"type": "number", "minimum": 0, "maximum": 1},
                    "summary": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "why_remembered": {"type": "string"},
                },
                "required": [
                    "type", "title", "text", "importance", "emotional_weight",
                    "valence", "arousal", "summary", "domains", "tags", "entities",
                    "why_remembered"
                ],
                "additionalProperties": False,
            },
        },
        "review_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["memory", "feel", "promise", "boundary"]},
                    "reason": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["kind", "reason", "text"],
                "additionalProperties": False,
            },
        },
        "board_message": {"type": "string"},
    },
    "required": [
        "summary", "feel", "feel_valence", "feel_arousal",
        "low_risk_memories", "review_items", "board_message"
    ],
    "additionalProperties": False,
}


def _recent_day_transcript() -> tuple[str, list[int]]:
    cutoff = time.time() - 24 * 60 * 60
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, direction, text, created_at
            FROM telegram_messages
            WHERE created_at >= ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()
    lines = []
    source_ids: list[int] = []
    for row in rows:
        source_ids.append(int(row["id"]))
        who = "User" if row["direction"] == "in" else "AI"
        lines.append(f"{who}: {row['text']}")
    return "\n".join(lines), source_ids


async def run_dream(reason: str = "manual") -> dict:
    transcript, source_message_ids = _recent_day_transcript()
    if not transcript.strip():
        return {"ok": False, "message": "no recent telegram messages"}
    prompt = f"""
Run a companion dream/feel digestion for the last day.

Return concise JSON only with this shape:
{{
  "summary": "daily relationship/life summary",
  "feel": "first-person relationship sediment from the AI role, not objective fact",
  "feel_valence": 0.5,
  "feel_arousal": 0.5,
  "low_risk_memories": [
    {{"type":"fact|event|pattern","title":"short title","text":"memory text","importance":0.1,"emotional_weight":0.1,"valence":0.5,"arousal":0.3,"summary":"retrieval summary","domains":["life"],"tags":["topic"],"entities":[],"why_remembered":"first-person reason"}}
  ],
  "review_items": [
    {{"kind":"memory|feel|promise|boundary","reason":"why user should review","text":"candidate text"}}
  ],
  "board_message": "one short message the AI could leave for the user"
}}

Transcript:
{transcript}

Existing companion context (do not duplicate it unless the day materially updates it):
{file_bundle(max_chars=8000)}
"""
    result = await ask_agent_json(prompt, DREAM_SCHEMA)
    if not result.ok:
        log("error", "dream failed", {"reason": reason, "stderr": result.stderr[-1000:]})
        return {"ok": False, "message": result.text}
    payload = result.data
    now = time.time()
    summary = str(payload.get("summary") or "").strip()
    feel = payload.get("feel", "")
    dream_id = f"dream_{int(now)}_{uuid.uuid4().hex[:6]}"
    with db() as conn:
        conn.execute(
            "INSERT INTO dream_runs(id, summary, feel, created_at) VALUES(?,?,?,?)",
            (dream_id, summary, feel, now),
        )

    append_memory_file("DREAM.md", time.strftime("%Y-%m-%d %H:%M"), summary)
    if feel:
        append_memory_file("FEEL.md", time.strftime("%Y-%m-%d %H:%M"), feel)
        await save_memory_candidate(
            {
                "type": "feel",
                "title": f"Feel {time.strftime('%Y-%m-%d')}",
                "text": feel,
                "importance": 0.7,
                "valence": float(payload.get("feel_valence", 0.5)),
                "arousal": float(payload.get("feel_arousal", 0.5)),
                "summary": summary,
                "domains": ["relationship"],
                "tags": ["feel", "dream"],
                "why_remembered": "这是我对共同经历的第一人称沉淀。",
            },
            source_message_ids=source_message_ids,
            allow_merge=False,
        )
        await propose_feel_crystallization(feel, source_message_ids)

    for mem in payload.get("low_risk_memories") or []:
        text = str(mem.get("text", "")).strip()
        if not text:
            continue
        await save_memory_candidate(
            {
                "type": mem.get("type", "event"),
                "title": mem.get("title", ""),
                "text": text,
                "importance": float(mem.get("importance", 0.5)),
                "emotional_weight": float(mem.get("emotional_weight", 0.0)),
                "valence": float(mem.get("valence", 0.5)),
                "arousal": float(mem.get("arousal", mem.get("emotional_weight", 0.3))),
                "summary": str(mem.get("summary", "")),
                "domains": mem.get("domains", []),
                "tags": mem.get("tags", []),
                "entities": mem.get("entities", []),
                "why_remembered": str(mem.get("why_remembered", "")),
            },
            source_message_ids=source_message_ids,
        )

    for item in payload.get("review_items") or []:
        item = dict(item)
        item["source_message_ids"] = source_message_ids
        review_id = f"review_{uuid.uuid4().hex}"
        with db() as conn:
            conn.execute(
                """
                INSERT INTO pending_reviews(id, kind, payload_json, reason, status, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    review_id,
                    item.get("kind", "memory"),
                    json.dumps(item, ensure_ascii=False),
                    item.get("reason", ""),
                    "pending",
                    now,
                    now,
                ),
            )

    board_text = (payload.get("board_message") or "").strip()
    if board_text:
        with db() as conn:
            conn.execute(
                "INSERT INTO board_messages(id, author, text, source, unread, created_at) VALUES(?,?,?,?,?,?)",
                (f"board_{uuid.uuid4().hex}", "ai", board_text, "dream", 1, now),
            )
        append_memory_file("BOARD.md", f"dream {time.strftime('%Y-%m-%d')}", board_text)

    log("info", "dream completed", {"reason": reason, "dream_id": dream_id, "runtime": "codex-subscription"})
    return {"ok": True, "id": dream_id, "summary": summary, "feel": feel}


def _local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.app_timezone))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def _dream_already_ran_today(now: datetime) -> bool:
    with db() as conn:
        row = conn.execute("SELECT created_at FROM dream_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        return False
    return datetime.fromtimestamp(float(row["created_at"]), tz=now.tzinfo).date() == now.date()


async def dream_loop() -> None:
    if not settings.dream_schedule_enabled:
        return
    while True:
        try:
            now = _local_now()
            if now.hour >= settings.dream_hour and not _dream_already_ran_today(now):
                await run_dream("scheduled")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("error", "scheduled dream failed", {"error": str(exc)})
        await asyncio.sleep(300)
