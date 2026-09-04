from __future__ import annotations

import asyncio
import json
import math
import time
from typing import Any

import httpx

from .config import settings
from .db import (
    db,
    log,
    memory_embedding_document,
    memory_embedding_hash,
    rows_to_dicts,
)


PROVIDER = "google-gemini"


class EmbeddingError(RuntimeError):
    pass


def embedding_available() -> bool:
    return bool(settings.gemini_embedding_enabled and settings.gemini_embedding_api_key)


def _dimensions() -> int:
    return max(128, min(3072, int(settings.gemini_embedding_dimensions)))


def _normalise(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= 0:
        raise EmbeddingError("Gemini returned a zero-length vector")
    return [value / magnitude for value in vector]


def cosine_dense(a: list[float], b: list[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    # Stored and query vectors are normalised on ingestion. Clamping absorbs
    # tiny floating-point drift around the cosine bounds.
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


def _prepared_text(text: str, task_type: str, title: str = "") -> str:
    if settings.gemini_embedding_model != "gemini-embedding-2":
        return text
    if task_type == "RETRIEVAL_QUERY":
        return f"task: search result | query: {text}"
    return f"title: {title or 'none'} | text: {text}"


async def generate_embedding(text: str, *, task_type: str, title: str = "") -> list[float]:
    if not embedding_available():
        raise EmbeddingError("Gemini embedding is not configured")
    model = settings.gemini_embedding_model
    embed_config: dict[str, Any] = {
        "outputDimensionality": _dimensions(),
        "autoTruncate": True,
    }
    payload: dict[str, Any] = {
        "content": {"parts": [{"text": _prepared_text(text, task_type, title)}]},
        "embedContentConfig": embed_config,
    }
    if model != "gemini-embedding-2":
        embed_config["taskType"] = task_type
        if task_type == "RETRIEVAL_DOCUMENT" and title.strip():
            embed_config["title"] = title.strip()
    url = f"{settings.gemini_embedding_base_url}/models/{model}:embedContent"
    try:
        async with httpx.AsyncClient(timeout=settings.gemini_embedding_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": settings.gemini_embedding_api_key,
                },
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        values = data.get("embedding", {}).get("values", [])
        vector = [float(value) for value in values]
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise EmbeddingError(str(exc)[:500]) from exc
    if len(vector) != _dimensions():
        raise EmbeddingError(
            f"Gemini returned {len(vector)} dimensions; expected {_dimensions()}"
        )
    # gemini-embedding-001 requires manual normalisation below 3072 dimensions.
    # Normalising all models is harmless and keeps the stored projection uniform.
    return _normalise(vector)


def reconcile_embedding_jobs(*, force: bool = False) -> int:
    """Ensure every active memory has a durable job for the current projection."""
    now = time.time()
    queued = 0
    with db() as conn:
        conn.execute("UPDATE embedding_jobs SET status='pending' WHERE status='processing'")
        rows = conn.execute(
            """
            SELECT m.*, e.provider AS embedding_provider, e.model AS embedding_model,
                   e.dimensions AS embedding_dimensions, e.content_hash AS embedding_hash
            FROM memory_items m
            LEFT JOIN memory_embeddings e ON e.memory_id=m.id
            WHERE m.approved=1 AND m.tombstoned=0
            """
        ).fetchall()
        for row in rows_to_dicts(rows):
            content_hash = memory_embedding_hash(row)
            current = (
                not force
                and row.get("embedding_provider") == PROVIDER
                and row.get("embedding_model") == settings.gemini_embedding_model
                and int(row.get("embedding_dimensions") or 0) == _dimensions()
                and row.get("embedding_hash") == content_hash
            )
            if current:
                conn.execute("DELETE FROM embedding_jobs WHERE memory_id=?", (row["id"],))
                continue
            if force:
                conn.execute("DELETE FROM memory_embeddings WHERE memory_id=?", (row["id"],))
            conn.execute(
                """
                INSERT INTO embedding_jobs(
                    memory_id, content_hash, status, attempts, next_attempt_at,
                    last_error, created_at, updated_at
                ) VALUES(?,?, 'pending', 0, 0, '', ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    content_hash=excluded.content_hash, status='pending', attempts=0,
                    next_attempt_at=0, last_error='', updated_at=excluded.updated_at
                """,
                (row["id"], content_hash, now, now),
            )
            queued += 1
    return queued


async def process_next_embedding_job() -> bool:
    if not embedding_available():
        return False
    now = time.time()
    with db() as conn:
        job = conn.execute(
            """
            SELECT * FROM embedding_jobs
            WHERE status IN ('pending', 'retry') AND next_attempt_at<=?
            ORDER BY created_at ASC LIMIT 1
            """,
            (now,),
        ).fetchone()
        if not job:
            return False
        memory_id = str(job["memory_id"])
        conn.execute(
            "UPDATE embedding_jobs SET status='processing', updated_at=? WHERE memory_id=?",
            (now, memory_id),
        )

    with db() as conn:
        row = conn.execute("SELECT * FROM memory_items WHERE id=?", (memory_id,)).fetchone()
    if not row or not int(row["approved"]) or int(row["tombstoned"]):
        with db() as conn:
            conn.execute("DELETE FROM embedding_jobs WHERE memory_id=?", (memory_id,))
        return True

    item = dict(row)
    content_hash = memory_embedding_hash(item)
    if content_hash != str(job["content_hash"]):
        with db() as conn:
            conn.execute(
                """
                UPDATE embedding_jobs SET content_hash=?, status='pending', attempts=0,
                    next_attempt_at=0, last_error='', updated_at=? WHERE memory_id=?
                """,
                (content_hash, time.time(), memory_id),
            )
        return True

    try:
        vector = await generate_embedding(
            memory_embedding_document(item),
            task_type="RETRIEVAL_DOCUMENT",
            title=str(item.get("title", "")),
        )
        with db() as conn:
            latest = conn.execute("SELECT * FROM memory_items WHERE id=?", (memory_id,)).fetchone()
            if not latest or memory_embedding_hash(dict(latest)) != content_hash:
                conn.execute(
                    "UPDATE embedding_jobs SET status='pending', updated_at=? WHERE memory_id=?",
                    (time.time(), memory_id),
                )
                return True
            conn.execute(
                """
                INSERT INTO memory_embeddings(
                    memory_id, provider, model, dimensions, content_hash, vector_json, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    provider=excluded.provider, model=excluded.model,
                    dimensions=excluded.dimensions, content_hash=excluded.content_hash,
                    vector_json=excluded.vector_json, updated_at=excluded.updated_at
                """,
                (
                    memory_id,
                    PROVIDER,
                    settings.gemini_embedding_model,
                    _dimensions(),
                    content_hash,
                    json.dumps(vector, separators=(",", ":")),
                    time.time(),
                ),
            )
            conn.execute("DELETE FROM embedding_jobs WHERE memory_id=?", (memory_id,))
        return True
    except EmbeddingError as exc:
        attempts = int(job["attempts"]) + 1
        delay = min(
            settings.gemini_embedding_retry_max_seconds,
            settings.gemini_embedding_retry_base_seconds * (2 ** min(attempts - 1, 8)),
        )
        with db() as conn:
            conn.execute(
                """
                UPDATE embedding_jobs SET status='retry', attempts=?, next_attempt_at=?,
                    last_error=?, updated_at=? WHERE memory_id=?
                """,
                (attempts, time.time() + delay, str(exc)[:500], time.time(), memory_id),
            )
        log("warning", "Gemini embedding job will retry", {"memory_id": memory_id, "error": str(exc)})
        return True


async def process_embedding_queue(*, limit: int = 100) -> int:
    processed = 0
    for _ in range(max(0, limit)):
        if not await process_next_embedding_job():
            break
        processed += 1
    return processed


async def vector_search(
    query: str,
    *,
    limit: int = 24,
    threshold: float | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    if not embedding_available() or not query.strip():
        return []
    query_vector = await generate_embedding(query.strip(), task_type="RETRIEVAL_QUERY")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT m.*, e.vector_json
            FROM memory_embeddings e
            JOIN memory_items m ON m.id=e.memory_id
            WHERE e.provider=? AND e.model=? AND e.dimensions=?
              AND m.approved=1 AND m.tombstoned=0
              AND (?=1 OR m.archived=0)
            """,
            (
                PROVIDER,
                settings.gemini_embedding_model,
                _dimensions(),
                1 if include_archived else 0,
            ),
        ).fetchall()
    minimum = settings.memory_vector_threshold if threshold is None else threshold
    scored: list[dict[str, Any]] = []
    for row in rows_to_dicts(rows):
        try:
            vector = [float(value) for value in json.loads(str(row.pop("vector_json")))]
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        similarity = cosine_dense(query_vector, vector)
        if similarity < minimum:
            continue
        row["_vector_score"] = similarity
        scored.append(row)
    scored.sort(key=lambda item: float(item["_vector_score"]), reverse=True)
    return scored[:limit]


def embedding_status() -> dict[str, Any]:
    with db() as conn:
        active = int(
            conn.execute(
                "SELECT COUNT(*) FROM memory_items WHERE approved=1 AND resolved=0 AND archived=0"
            ).fetchone()[0]
        )
        indexed = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM memory_embeddings e
                JOIN memory_items m ON m.id=e.memory_id
                WHERE e.provider=? AND e.model=? AND e.dimensions=?
                  AND m.approved=1 AND m.resolved=0 AND m.archived=0
                """,
                (PROVIDER, settings.gemini_embedding_model, _dimensions()),
            ).fetchone()[0]
        )
        pending = int(conn.execute("SELECT COUNT(*) FROM embedding_jobs").fetchone()[0])
        last_error_row = conn.execute(
            "SELECT last_error FROM embedding_jobs WHERE last_error!='' ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return {
        "mode": "gemini-vector-hybrid",
        "provider": PROVIDER,
        "enabled": settings.gemini_embedding_enabled,
        "configured": bool(settings.gemini_embedding_api_key),
        "model": settings.gemini_embedding_model,
        "dimensions": _dimensions(),
        "active_memories": active,
        "indexed": indexed,
        "pending": pending,
        "last_error": str(last_error_row[0]) if last_error_row else "",
        "local_model": False,
    }


async def embedding_worker_loop() -> None:
    reconcile_embedding_jobs()
    if not embedding_available():
        return
    while True:
        try:
            processed = await process_embedding_queue(limit=1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log("error", "embedding worker failed", {"error": str(exc)})
            processed = 0
        if not processed:
            await asyncio.sleep(max(1.0, settings.gemini_embedding_poll_seconds))
