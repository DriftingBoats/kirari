from __future__ import annotations

import json
import re
import time
import uuid

from .db import db, log, upsert_memory_item
from .hermes_client import ask_hermes
from .memory_files import append_memory_file, read_memory_file
from .retrieval import simple_embedding


def _recent_day_transcript() -> str:
    cutoff = time.time() - 24 * 60 * 60
    with db() as conn:
        rows = conn.execute(
            """
            SELECT direction, text, created_at
            FROM telegram_messages
            WHERE created_at >= ?
            ORDER BY created_at ASC
            """,
            (cutoff,),
        ).fetchall()
    lines = []
    for row in rows:
        who = "User" if row["direction"] == "in" else "AI"
        lines.append(f"{who}: {row['text']}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


async def run_dream(reason: str = "manual") -> dict:
    transcript = _recent_day_transcript()
    if not transcript.strip():
        return {"ok": False, "message": "no recent telegram messages"}
    prompt = f"""
Run a companion dream/feel digestion for the last day.

Return concise JSON only with this shape:
{{
  "summary": "daily relationship/life summary",
  "feel": "first-person relationship sediment from the AI role, not objective fact",
  "low_risk_memories": [
    {{"type":"fact|event|pattern","title":"short title","text":"memory text","importance":0.1,"emotional_weight":0.1}}
  ],
  "review_items": [
    {{"kind":"memory|feel|promise|boundary","reason":"why user should review","text":"candidate text"}}
  ],
  "board_message": "one short message the AI could leave for the user"
}}

Transcript:
{transcript}
"""
    result = await ask_hermes(prompt)
    payload = _extract_json_object(result.text)
    now = time.time()
    summary = payload.get("summary") or result.text[:1200]
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

    for mem in payload.get("low_risk_memories") or []:
        text = str(mem.get("text", "")).strip()
        if not text:
            continue
        mem_id = f"mem_{uuid.uuid4().hex}"
        upsert_memory_item(
            {
                "id": mem_id,
                "type": mem.get("type", "event"),
                "title": mem.get("title", ""),
                "text": text,
                "importance": float(mem.get("importance", 0.5)),
                "emotional_weight": float(mem.get("emotional_weight", 0.0)),
                "embedding_json": json.dumps(simple_embedding(text), ensure_ascii=False),
            }
        )
        append_memory_file("MEMORY.md", mem.get("title", "Memory"), text)

    for item in payload.get("review_items") or []:
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

    log("info", "dream completed", {"reason": reason, "dream_id": dream_id, "hermes_ok": result.ok})
    return {"ok": True, "id": dream_id, "summary": summary, "feel": feel}
