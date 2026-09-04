from __future__ import annotations

import asyncio
import time
from typing import Any

from .config import settings
from .db import db, log, rows_to_dicts
from .memory_service import archive_memory
from .memory_store import persist_bucket
from .retrieval import memory_vitality


IMMUNE_TYPES = {"pinned", "feel", "promise", "boundary", "plan", "letter"}
MIN_AGE_DAYS = 7.0


def memory_lifecycle_status() -> dict[str, Any]:
    with db() as conn:
        active = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE archived=0").fetchone()[0])
        archived = int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE archived=1 AND tombstoned=0"
            ).fetchone()[0]
        )
        tombstoned = int(conn.execute("SELECT COUNT(*) FROM memory_items WHERE tombstoned=1").fetchone()[0])
    return {
        "enabled": settings.memory_decay_enabled,
        "lambda": settings.memory_decay_lambda,
        "threshold": settings.memory_decay_threshold,
        "interval_hours": settings.memory_decay_interval_hours,
        "minimum_age_days": MIN_AGE_DAYS,
        "active": active,
        "archived": archived,
        "tombstoned": tombstoned,
    }


def run_memory_decay(*, apply: bool = False) -> dict[str, Any]:
    """Preview or apply natural forgetting.

    Forgetting archives derived memory records; it never destroys the source
    conversation. Pinned and boundary-like records are immune.
    """
    now = time.time()
    cutoff = now - MIN_AGE_DAYS * 86400
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM memory_items
            WHERE archived=0 AND tombstoned=0 AND pinned=0 AND created_at<=?
            """,
            (cutoff,),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for item in rows_to_dicts(rows):
        if str(item.get("type", "")).lower() in IMMUNE_TYPES:
            continue
        days_since = max(0.0, (now - float(item.get("last_active") or item.get("created_at") or now)) / 86400.0)
        if (
            not int(item.get("resolved", 0))
            and float(item.get("importance", 0.5)) <= 0.4
            and days_since > 30.0
        ):
            item["resolved"] = 1
            if apply:
                persist_bucket(item, "auto_resolved", detail="low importance and inactive for 30 days")
        score = memory_vitality(item, now=now)
        if score >= settings.memory_decay_threshold:
            continue
        candidates.append(
            {
                "id": str(item["id"]),
                "title": str(item.get("title", "")),
                "type": str(item.get("type", "memory")),
                "score": round(score, 4),
            }
        )

    if apply and candidates:
        ids = [item["id"] for item in candidates]
        for memory_id in ids:
            archive_memory(memory_id, reason="natural decay")
        log("info", "memory decay archived records", {"count": len(ids), "ids": ids})

    return {
        "ok": True,
        "applied": apply,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


async def memory_decay_loop() -> None:
    if not settings.memory_decay_enabled:
        return
    while True:
        try:
            await asyncio.to_thread(run_memory_decay, apply=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("error", "memory decay cycle failed", {"error": str(exc)})
        await asyncio.sleep(max(3600.0, settings.memory_decay_interval_hours * 3600.0))
