from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent import ask_agent
from .config import settings
from .db import db, log
from .memory_files import append_memory_file
from .retrieval import recent_telegram_context


def _local_now() -> datetime:
    try:
        return datetime.now(ZoneInfo(settings.app_timezone))
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone()


def _is_quiet_hour(hour: int) -> bool:
    start = settings.proactive_quiet_start % 24
    end = settings.proactive_quiet_end % 24
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def proactive_due(now_ts: float | None = None) -> tuple[bool, int | None]:
    if not settings.proactive_enabled or not settings.telegram_bot_token:
        return False, None
    now_ts = now_ts or time.time()
    if _is_quiet_hour(_local_now().hour):
        return False, None
    with db() as conn:
        last_in = conn.execute(
            """
            SELECT chat_id, created_at FROM telegram_messages
            WHERE direction='in' AND user_id != 0
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
        last_proactive = conn.execute(
            "SELECT created_at FROM board_messages WHERE source='proactive' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not last_in:
        return False, None
    if now_ts - float(last_in["created_at"]) < settings.proactive_idle_hours * 3600:
        return False, None
    if last_proactive and now_ts - float(last_proactive["created_at"]) < settings.proactive_cooldown_hours * 3600:
        return False, None
    return True, int(last_in["chat_id"])


async def run_proactive_once(send_func: Callable[[int, str], Awaitable[None]]) -> dict:
    due, chat_id = proactive_due()
    if not due or chat_id is None:
        return {"ok": True, "sent": False}
    recent = recent_telegram_context(chat_id, min(settings.recent_message_limit, 12))
    result = await ask_agent(
        "The user has been away for a while. Write one gentle, specific check-in that grows naturally from the relationship context. "
        "Do not guilt them, demand a reply, mention their absence duration, or claim you were waiting. Keep it to 1-3 short sentences.",
        recent_context=recent,
    )
    if not result.ok:
        log("error", "proactive message generation failed", {"stderr": result.stderr[-1000:]})
        return {"ok": False, "sent": False, "message": result.text}
    text = result.text.strip()
    await send_func(chat_id, text)
    now = time.time()
    with db() as conn:
        conn.execute(
            """
            INSERT INTO telegram_messages(telegram_message_id, chat_id, user_id, direction, text, raw_json, created_at)
            VALUES(NULL,?,?,?,?,?,?)
            """,
            (chat_id, 0, "out", text, json.dumps({"source": "proactive"}), now),
        )
        conn.execute(
            "INSERT INTO board_messages(id, author, text, source, unread, pushed_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (f"board_{uuid.uuid4().hex}", "ai", text, "proactive", 1, now, now),
        )
    append_memory_file("BOARD.md", f"proactive {time.strftime('%Y-%m-%d')}", text)
    log("info", "proactive message sent", {"chat_id": chat_id})
    return {"ok": True, "sent": True}


async def proactive_loop(send_func: Callable[[int, str], Awaitable[None]]) -> None:
    while True:
        try:
            await run_proactive_once(send_func)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("error", "proactive loop failed", {"error": str(exc)})
        await asyncio.sleep(300)
