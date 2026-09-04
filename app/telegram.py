from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from typing import Any

import httpx
from fastapi import Header, HTTPException, Request

from .config import settings
from .companion import generate_companion_reply
from .db import db, log
from .retrieval import (
    conversation_is_cold,
    recall_memories_with_codex,
    recent_telegram_context,
    render_recalled,
    surface_memories,
)


_chat_locks: dict[int, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task] = set()


def _telegram_api_url(method: str) -> str:
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"


def _safe_http_error(action: str, response: httpx.Response | None = None) -> str:
    if response is not None:
        return f"Telegram {action} failed with HTTP {response.status_code}"
    return f"Telegram {action} request failed"


def _message_chunks(text: str, limit: int = 3900) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, limit)
        if split_at < limit // 3:
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 3:
            split_at = remaining.rfind("。", 0, limit)
            if split_at >= 0:
                split_at += 1
        if split_at < limit // 3:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return [chunk for chunk in chunks if chunk]


async def send_message(chat_id: int, text: str) -> None:
    if not settings.telegram_bot_token:
        log("warning", "Telegram token is not configured", {"chat_id": chat_id, "text": text[:120]})
        return
    async with httpx.AsyncClient(timeout=20) as client:
        for chunk in _message_chunks(text):
            response = await client.post(_telegram_api_url("sendMessage"), json={"chat_id": chat_id, "text": chunk})
            if response.is_error:
                raise RuntimeError(_safe_http_error("sendMessage", response))


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
) -> int | None:
    try:
        with db() as conn:
            cursor = conn.execute(
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
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        return None


async def _typing_loop(chat_id: int) -> None:
    while True:
        try:
            await send_typing(chat_id)
        except Exception:
            pass
        await asyncio.sleep(4)


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

    lock = _chat_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        cold_start = conversation_is_cold(chat_id)
        message_row_id = save_telegram_message(
            telegram_message_id=message.get("message_id"),
            chat_id=chat_id,
            user_id=user_id,
            direction="in",
            text=text,
            raw=message,
        )
        if message_row_id is None:
            return
        typing_task = asyncio.create_task(_typing_loop(chat_id))
        try:
            recalled_items = await recall_memories_with_codex(text)
            if cold_start:
                recalled_ids = {str(item["id"]) for item in recalled_items}
                recalled_items.extend(
                    item for item in surface_memories()
                    if str(item["id"]) not in recalled_ids
                )
            recalled = render_recalled(recalled_items)
            recent = recent_telegram_context(
                chat_id, settings.recent_message_limit, exclude_row_id=message_row_id
            )
            result = await generate_companion_reply(
                text,
                recent_context=recent,
                recalled_context=recalled,
                recalled_items=recalled_items,
                source_message_ids=[message_row_id],
            )
            reply = result.text.strip()
            if not result.ok:
                log(
                    "error",
                    "Codex subscription response failed",
                    {"stderr": result.stderr[-1200:], "returncode": result.returncode},
                )
            await send_message(chat_id, reply)
            save_telegram_message(
                telegram_message_id=None,
                chat_id=chat_id,
                user_id=user_id,
                direction="out",
                text=reply,
                raw={
                    "codex_ok": result.ok,
                    "returncode": result.returncode,
                    "review_ids": result.data.get("review_ids", []),
                    "reinforced_memory_ids": result.data.get("reinforced_memory_ids", []),
                },
            )
        finally:
            typing_task.cancel()
            await asyncio.gather(typing_task, return_exceptions=True)


def _task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc:
        log("error", "Telegram background task failed", {"error": str(exc)})


async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict[str, bool]:
    if settings.telegram_mode != "webhook":
        raise HTTPException(status_code=409, detail="Telegram is configured for polling mode")
    if not settings.telegram_webhook_secret:
        raise HTTPException(status_code=503, detail="Telegram webhook secret is not configured")
    if settings.telegram_webhook_secret and x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="invalid secret")
    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if message:
        task = asyncio.create_task(handle_text_message(message))
        _background_tasks.add(task)
        task.add_done_callback(_task_done)
    return {"ok": True}


async def telegram_polling_loop() -> None:
    if not settings.telegram_bot_token or settings.telegram_mode != "polling":
        return
    offset: int | None = None
    timeout = min(max(settings.telegram_poll_timeout_seconds, 5), 50)
    async with httpx.AsyncClient(timeout=timeout + 10) as client:
        try:
            response = await client.post(
                _telegram_api_url("deleteWebhook"),
                json={"drop_pending_updates": False},
            )
            if response.is_error:
                raise RuntimeError(_safe_http_error("deleteWebhook", response))
        except Exception as exc:
            log("warning", "could not switch Telegram to polling mode", {"error": type(exc).__name__})
        while True:
            try:
                payload: dict[str, Any] = {
                    "timeout": timeout,
                    "allowed_updates": ["message", "edited_message"],
                }
                if offset is not None:
                    payload["offset"] = offset
                response = await client.post(_telegram_api_url("getUpdates"), json=payload)
                if response.is_error:
                    raise RuntimeError(_safe_http_error("getUpdates", response))
                body = response.json()
                updates = body.get("result") if body.get("ok") else []
                handlers = []
                for update in updates or []:
                    offset = max(offset or 0, int(update.get("update_id", 0)) + 1)
                    message = update.get("message") or update.get("edited_message")
                    if message:
                        handlers.append(handle_text_message(message))
                if handlers:
                    results = await asyncio.gather(*handlers, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception):
                            log("error", "Telegram polling message failed", {"error": str(result)})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log("error", "Telegram polling failed", {"error": str(exc).replace(settings.telegram_bot_token, "[redacted]")})
                await asyncio.sleep(5)
