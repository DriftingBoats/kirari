from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent import AgentResult, ask_agent_json, build_companion_prompt
from .config import settings
from .db import db


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "review_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["memory", "feel", "promise", "boundary", "reminder", "calendar"],
                    },
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "reason": {"type": "string"},
                    "when": {"type": "string"},
                    "repeat_rule": {"type": "string"},
                    "layer": {"type": "string", "enum": ["life", "relationship", "work"]},
                    "summary": {"type": "string"},
                    "domains": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "entities": {"type": "array", "items": {"type": "string"}},
                    "valence": {"type": "number", "minimum": 0, "maximum": 1},
                    "arousal": {"type": "number", "minimum": 0, "maximum": 1},
                    "importance": {"type": "number", "minimum": 0, "maximum": 1},
                    "why_remembered": {"type": "string"},
                },
                "required": [
                    "kind", "title", "text", "reason", "when", "repeat_rule", "layer",
                    "summary", "domains", "tags", "entities", "valence", "arousal",
                    "importance", "why_remembered"
                ],
                "additionalProperties": False,
            },
        },
        "used_memory_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reply", "review_items", "used_memory_ids"],
    "additionalProperties": False,
}


def _local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.app_timezone))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def _save_review_items(items: list[dict], source_message_ids: list[int] | None = None) -> list[str]:
    saved: list[str] = []
    now = time.time()
    with db() as conn:
        for item in items[:6]:
            kind = str(item.get("kind", "")).strip().lower()
            text = str(item.get("text", "")).strip()
            if kind not in {"memory", "feel", "promise", "boundary", "reminder", "calendar"} or not text:
                continue
            review_id = f"review_{uuid.uuid4().hex}"
            item = dict(item)
            item["source_message_ids"] = list(source_message_ids or [])
            conn.execute(
                """
                INSERT INTO pending_reviews(id, kind, payload_json, reason, status, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    review_id,
                    kind,
                    json.dumps(item, ensure_ascii=False),
                    str(item.get("reason", "")).strip(),
                    "pending",
                    now,
                    now,
                ),
            )
            saved.append(review_id)
    return saved


async def generate_companion_reply(
    user_text: str,
    recent_context: str = "",
    recalled_context: str = "",
    recalled_items: list[dict] | None = None,
    source_message_ids: list[int] | None = None,
) -> AgentResult:
    now = _local_now()
    prompt = build_companion_prompt(user_text, recent_context, recalled_context)
    prompt += f"""

Return JSON matching the supplied schema.
- `reply` is the natural companion reply the user will see.
- `review_items` is usually empty.
- `used_memory_ids` contains only recalled memory IDs that materially affected
  the reply. Never include an ID merely because it was shown to you.
- Add a review item only when the user clearly states a durable personal fact worth remembering,
  asks to pin a promise/boundary, or explicitly asks for a reminder/calendar event.
- Never claim an action was completed. Say it was prepared for confirmation when relevant.
- For reminder/calendar items, `when` must be an ISO 8601 timestamp with UTC offset.
- Use repeat_rule only as one of: empty, daily, weekly, monthly.
- Use layer=life unless relationship or work is clearly more suitable.
- For durable memory candidates, add a factual summary, 1-3 domains, useful
  search tags/entities, Russell valence/arousal coordinates, importance, and a
  concrete first-person reason this continuity matters.
- Preserve the user's meaning. Do not diagnose personality or promote a
  transient mood into a stable identity claim.
- For non-memory actions, return neutral/empty memory metadata fields.

Current local time: {now.isoformat()} ({settings.app_timezone})
"""
    result = await ask_agent_json(prompt, REPLY_SCHEMA)
    if not result.ok:
        return result
    reply = str(result.data.get("reply", "")).strip()
    if not reply:
        return AgentResult(ok=False, text="我刚才没有组织好语言，可以再对我说一次吗？")
    review_ids = _save_review_items(
        result.data.get("review_items") or [], source_message_ids=source_message_ids
    )
    available_ids = {str(item.get("id")) for item in (recalled_items or [])}
    used_ids = [
        str(memory_id) for memory_id in result.data.get("used_memory_ids", [])
        if str(memory_id) in available_ids
    ]
    if used_ids:
        import asyncio

        from .memory_service import reinforce_memory

        for memory_id in used_ids:
            await asyncio.to_thread(reinforce_memory, memory_id)
    result.text = reply
    result.data["review_ids"] = review_ids
    result.data["reinforced_memory_ids"] = used_ids
    return result
