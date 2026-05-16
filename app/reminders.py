from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

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


def mark_sent(reminder_id: str) -> None:
    now = time.time()
    with db() as conn:
        conn.execute(
            "UPDATE reminders SET sent_at=?, status='sent', updated_at=? WHERE id=?",
            (now, now, reminder_id),
        )


def _last_chat_id() -> int | None:
    with db() as conn:
        row = conn.execute(
            "SELECT chat_id FROM telegram_messages WHERE direction='in' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return int(row["chat_id"]) if row else None
