from __future__ import annotations

import json
import time
from typing import Any

import httpx
from fastapi import Header, HTTPException, Request

from .config import settings
from .db import db, log
from .hermes_client import ask_hermes
from .retrieval import recall_memories, recent_telegram_context, render_recalled


def _telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


async def send_message(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        log("warning", "Telegram token is not configured", {"chat_id": chat_id, "text": text[:120]})
        return
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(_telegram_api_url("sendMessage"), json={"chat_id": chat_id, "text": text})


async def send_typing(chat_id: int) -> None:
    if not settings.telegram_bot_token:
        return
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(_telegram_api_url("sendChatAction"), json={"chat_id": chat_id, "action": "typing"})


def allowed_user(user_id: int) -> bool:
    allowed = settings.telegram_allowed_user_ids
    return not allowed or user_id in allowed


def save_telegram_message(
    *,
    telegram_message_id: int | None,
    chat_id: int,
    user_id: int,
    direction: str,
    text: str,
    raw: dict[str, Any] | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO telegram_messages(
                telegram_message_id, chat_id, user_id, direction, text, raw_json, created_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                telegram_message_id,
                chat_id,
                user_id,
                direction,
                text,
                json.dumps(raw or {}, ensure_ascii=False),
                time.time(),
            ),
        )


async def handle_text_message(message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    user = message.get("from") or {}
    chat_id = int(chat.get("id"))
    user_id = int(user.get("id"))
    text = (message.get("text") or message.get("caption") or "").strip()
    if not text:
        return
    if not allowed_user(user_id):
        await send_message(chat_id, "This bot is private.")
        return

    save_telegram_message(
        telegram_message_id=message.get("message_id"),
        chat_id=chat_id,
        user_id=user_id,
        direction="in",
        text=text,
        raw=message,
    )
    await send_typing(chat_id)
    recalled = render_recalled(recall_memories(text))
    recent = recent_telegram_context(chat_id, settings.recent_message_limit)
    result = await ask_hermes(text, recent_context=recent, recalled_context=recalled)
    reply = result.text.strip()
    if not result.ok:
        reply = f"我这边 Hermes 还没连好：{reply}"
        log("error", "Hermes response failed", {"stderr": result.stderr, "returncode": result.returncode})
    await send_message(chat_id, reply)
    save_telegram_message(
        telegram_message_id=None,
        chat_id=chat_id,
        user_id=user_id,
        direction="out",
        text=reply,
        raw={"hermes_ok": result.ok, "stderr": result.stderr, "returncode": result.returncode},
    )


async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, bool]:
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="invalid secret")
    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if message:
        await handle_text_message(message)
    return {"ok": True}
