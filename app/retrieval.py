from __future__ import annotations

import json
import math
import re
from typing import Any

from .db import db, rows_to_dicts


def _tokens(text: str) -> set[str]:
    text = text.lower()
    words = re.findall(r"[\w\u4e00-\u9fff]{2,}", text)
    return set(words)


def simple_embedding(text: str) -> dict[str, float]:
    toks = _tokens(text)
    if not toks:
        return {}
    weight = 1.0 / math.sqrt(len(toks))
    return {tok: weight for tok in toks}


def cosine_sparse(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def recall_memories(query: str, limit: int = 8) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return []
    query_embedding = simple_embedding(query)
    candidates: dict[str, dict[str, Any]] = {}
    with db() as conn:
        try:
            rows = conn.execute(
                """
                SELECT m.*, bm25(memory_items_fts) AS rank
                FROM memory_items_fts f
                JOIN memory_items m ON m.id = f.id
                WHERE memory_items_fts MATCH ?
                  AND m.approved = 1
                  AND m.resolved = 0
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit * 3),
            ).fetchall()
            for row in rows:
                d = dict(row)
                d["_fts_score"] = 1.0
                candidates[d["id"]] = d
        except Exception:
            pass

        rows = conn.execute(
            "SELECT * FROM memory_items WHERE approved=1 AND resolved=0 ORDER BY importance DESC, updated_at DESC LIMIT 200"
        ).fetchall()
        for row in rows:
            d = dict(row)
            candidates.setdefault(d["id"], d)

    scored: list[dict[str, Any]] = []
    for item in candidates.values():
        emb_raw = item.get("embedding_json")
        try:
            emb = json.loads(emb_raw) if emb_raw else simple_embedding(item.get("text", ""))
        except json.JSONDecodeError:
            emb = simple_embedding(item.get("text", ""))
        semantic = cosine_sparse(query_embedding, emb)
        score = semantic * 0.55 + float(item.get("_fts_score", 0.0)) * 0.25
        score += float(item.get("importance", 0.5)) * 0.15
        score += float(item.get("emotional_weight", 0.0)) * 0.05
        item["_score"] = score
        if score > 0:
            scored.append(item)
    scored.sort(key=lambda x: x.get("_score", 0), reverse=True)
    return scored[:limit]


def render_recalled(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = []
    for item in items:
        label = item.get("type", "memory")
        title = item.get("title") or label
        text = (item.get("text") or "").strip()
        lines.append(f"- [{label}] {title}: {text}")
    return "\n".join(lines)


def recent_telegram_context(chat_id: int, limit: int) -> str:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT direction, text, created_at
            FROM telegram_messages
            WHERE chat_id=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    messages = list(reversed(rows_to_dicts(rows)))
    rendered: list[str] = []
    for msg in messages:
        who = "User" if msg["direction"] == "in" else "AI"
        rendered.append(f"{who}: {msg['text']}")
    return "\n".join(rendered)
