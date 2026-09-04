from __future__ import annotations

import asyncio
import calendar
import time
from datetime import datetime, timedelta
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import settings
from .db import db, log, rows_to_dicts


async def reminder_loop(send_func: Callable[[int, str], Awaitable[None]]) -> None:
    while True:
        try:
            due = due_reminders()
            for item in due:
                chat_id = _last_chat_id()
                if chat_id:
                    await send_func(chat_id, f"提醒：{item['title']}\n{item.get('description') or ''}".strip())
                    mark_sent(item["id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("error", "reminder loop failed", {"error": str(exc)})
        await asyncio.sleep(30)


def due_reminders() -> list[dict]:
    now = time.time()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE status='pending'
              AND sent_at IS NULL
              AND remind_at <= ?
            ORDER BY remind_at ASC
            LIMIT 10
            """,
            (now,),
        ).fetchall()
    return rows_to_dicts(rows)


def _next_occurrence(timestamp: float, repeat_rule: str) -> float | None:
    try:
        tz = ZoneInfo(settings.app_timezone)
    except ZoneInfoNotFoundError:
        tz = datetime.now().astimezone().tzinfo
    current = datetime.fromtimestamp(timestamp, tz=tz)
    if repeat_rule == "daily":
        return (current + timedelta(days=1)).timestamp()
    if repeat_rule == "weekly":
        return (current + timedelta(days=7)).timestamp()
    if repeat_rule == "monthly":
        year = current.year + (1 if current.month == 12 else 0)
        month = 1 if current.month == 12 else current.month + 1
        day = min(current.day, calendar.monthrange(year, month)[1])
        return current.replace(year=year, month=month, day=day).timestamp()
    return None


def mark_sent(reminder_id: str) -> None:
    now = time.time()
    with db() as conn:
        row = conn.execute("SELECT remind_at, repeat_rule FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not row:
            return
        next_at = _next_occurrence(float(row["remind_at"]), str(row["repeat_rule"] or ""))
        if next_at is None:
            conn.execute(
                "UPDATE reminders SET sent_at=?, status='sent', updated_at=? WHERE id=?",
                (now, now, reminder_id),
            )
        else:
            while next_at <= now:
                following = _next_occurrence(next_at, str(row["repeat_rule"]))
                if following is None:
                    break
                next_at = following
            conn.execute(
                "UPDATE reminders SET remind_at=?, sent_at=NULL, status='pending', updated_at=? WHERE id=?",
                (next_at, now, reminder_id),
            )


def snooze(reminder_id: str, seconds: int) -> bool:
    seconds = min(max(seconds, 60), 30 * 24 * 60 * 60)
    with db() as conn:
        cursor = conn.execute(
            "UPDATE reminders SET remind_at=?, sent_at=NULL, status='pending', updated_at=? WHERE id=?",
            (time.time() + seconds, time.time(), reminder_id),
        )
    return cursor.rowcount > 0


def _last_chat_id() -> int | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT chat_id FROM telegram_messages
            WHERE direction='in' AND user_id != 0
            ORDER BY created_at DESC LIMIT 1
            """
        ).fetchone()
    return int(row["chat_id"]) if row else None
