from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

from rapidfuzz import fuzz

from .config import settings
from .db import db, rows_to_dicts
from .memory_files import remove_memory_block
from .memory_store import persist_bucket


REGULAR_TYPES = {"memory", "fact", "event", "pattern"}
PROTECTED_TYPES = {"pinned", "feel", "promise", "boundary", "plan", "letter", "permanent"}


def _list_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalised_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def get_memory(memory_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM memory_items WHERE id=?", (memory_id,)).fetchone()
    return dict(row) if row else None


def _compatible_types(left: str, right: str) -> bool:
    if left == right:
        return True
    return left in REGULAR_TYPES and right in REGULAR_TYPES


async def _find_merge_candidate(item: dict[str, Any]) -> tuple[dict[str, Any] | None, float]:
    text = str(item.get("text", "")).strip()
    if not text:
        return None, 0.0
    with db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM memory_items
                WHERE approved=1 AND archived=0 AND tombstoned=0
                ORDER BY updated_at DESC LIMIT ?
                """,
                (max(settings.memory_catalog_limit, 500),),
            ).fetchall()
        )
    for candidate in rows:
        if _normalised_text(str(candidate.get("text", ""))) == _normalised_text(text):
            if _compatible_types(str(candidate.get("type", "memory")), str(item.get("type", "memory"))):
                return candidate, 1.0

    from .embeddings import EmbeddingError, embedding_available, vector_search

    if embedding_available():
        try:
            vector_matches = await vector_search(
                text,
                limit=8,
                threshold=settings.memory_merge_threshold,
                include_archived=False,
            )
            for candidate in vector_matches:
                if _compatible_types(
                    str(candidate.get("type", "memory")), str(item.get("type", "memory"))
                ):
                    return candidate, float(candidate.get("_vector_score", 0.0))
        except EmbeddingError:
            pass

    best: dict[str, Any] | None = None
    best_score = 0.0
    for candidate in rows:
        if not _compatible_types(
            str(candidate.get("type", "memory")), str(item.get("type", "memory"))
        ):
            continue
        score = fuzz.WRatio(text, str(candidate.get("text", ""))) / 100.0
        if score > best_score:
            best, best_score = candidate, score
    return (best, best_score) if best_score >= settings.memory_merge_threshold else (None, best_score)


def _merge_lists(left: Any, right: Any) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in [*_list_value(left), *_list_value(right)]:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _merge_items(existing: dict[str, Any], incoming: dict[str, Any], score: float) -> dict[str, Any]:
    merged = dict(existing)
    existing_text = str(existing.get("text", "")).strip()
    incoming_text = str(incoming.get("text", "")).strip()
    if _normalised_text(existing_text) != _normalised_text(incoming_text):
        merged["text"] = f"{existing_text}\n\n---\n\n{incoming_text}".strip()
    merged["summary"] = str(incoming.get("summary") or existing.get("summary") or "")
    merged["title"] = str(existing.get("title") or incoming.get("title") or "")
    merged["importance"] = max(
        float(existing.get("importance", 0.5)), float(incoming.get("importance", 0.5))
    )
    for field in ("domains_json", "tags_json", "entities_json", "source_message_ids"):
        incoming_key = field.replace("_json", "")
        merged[field] = _merge_lists(existing.get(field), incoming.get(field, incoming.get(incoming_key, [])))
    old_count = max(1.0, float(existing.get("activation_count", 0)) + 1.0)
    merged["valence"] = (
        float(existing.get("valence", 0.5)) * old_count + float(incoming.get("valence", 0.5))
    ) / (old_count + 1.0)
    merged["arousal"] = max(
        float(existing.get("arousal", 0.3)), float(incoming.get("arousal", 0.3))
    )
    lineage = _dict_value(existing.get("lineage_json"))
    lineage.setdefault("merged_from", []).append(
        {"at": time.time(), "incoming_id": incoming.get("id"), "similarity": round(score, 4)}
    )
    merged["lineage"] = lineage
    merged["lineage_json"] = lineage
    return merged


async def save_memory_candidate(
    item: dict[str, Any],
    *,
    source_message_ids: list[int] | None = None,
    allow_merge: bool = True,
    action: str = "created",
) -> dict[str, Any]:
    now = time.time()
    item = dict(item)
    item.setdefault("id", f"mem_{uuid.uuid4().hex}")
    item.setdefault("type", "event")
    item.setdefault("created_at", now)
    item.setdefault("last_active", now)
    item.setdefault("approved", 1)
    item.setdefault("archived", 0)
    item.setdefault("tombstoned", 0)
    item["source_message_ids"] = _merge_lists(
        item.get("source_message_ids", []), source_message_ids or []
    )
    if allow_merge and str(item.get("type", "memory")) not in PROTECTED_TYPES:
        candidate, score = await _find_merge_candidate(item)
        if candidate:
            merged = _merge_items(candidate, item, score)
            saved = persist_bucket(
                merged,
                "merged",
                detail=f"similarity={score:.4f}",
                related_id=str(item["id"]),
            )
            return {"item": saved, "created": False, "merged_into": saved["id"], "score": score}
    saved = persist_bucket(item, action)
    return {"item": saved, "created": True, "merged_into": None, "score": 0.0}


def archive_memory(memory_id: str, *, reason: str = "decay") -> dict[str, Any] | None:
    item = get_memory(memory_id)
    if not item or int(item.get("tombstoned", 0)):
        return None
    item["archived"] = 1
    item["archived_at"] = time.time()
    saved = persist_bucket(item, "archived", detail=reason)
    remove_memory_block(memory_id)
    return saved


def restore_memory(memory_id: str) -> dict[str, Any] | None:
    item = get_memory(memory_id)
    if not item or int(item.get("tombstoned", 0)):
        return None
    item["archived"] = 0
    item["archived_at"] = None
    item["resolved"] = 0
    item["last_active"] = time.time()
    return persist_bucket(item, "restored")


def tombstone_memory(memory_id: str, *, reason: str = "user request") -> dict[str, Any] | None:
    item = get_memory(memory_id)
    if not item:
        return None
    item["archived"] = 1
    item["tombstoned"] = 1
    item["deleted_at"] = time.time()
    saved = persist_bucket(item, "tombstoned", detail=reason)
    remove_memory_block(memory_id)
    return saved


def reinforce_memory(memory_id: str) -> dict[str, Any] | None:
    item = get_memory(memory_id)
    if not item or int(item.get("archived", 0)) or int(item.get("tombstoned", 0)):
        return None
    now = time.time()
    item["activation_count"] = float(item.get("activation_count", 0)) + 1.0
    item["last_active"] = now
    saved = persist_bucket(item, "reinforced")

    created = float(item.get("created_at", now))
    with db() as conn:
        neighbours = rows_to_dicts(
            conn.execute(
                """
                SELECT * FROM memory_items
                WHERE id!=? AND archived=0 AND tombstoned=0
                  AND ABS(created_at-?)<=? ORDER BY ABS(created_at-?) LIMIT 5
                """,
                (memory_id, created, 48 * 3600, created),
            ).fetchall()
        )
    for neighbour in neighbours:
        neighbour["activation_count"] = float(neighbour.get("activation_count", 0)) + 0.3
        persist_bucket(neighbour, "time_ripple", related_id=memory_id)
    return saved


async def propose_feel_crystallization(text: str, source_message_ids: list[int]) -> str | None:
    """Suggest a pinned insight when the same feeling has formed repeatedly."""
    from .embeddings import EmbeddingError, embedding_available, vector_search

    if not embedding_available() or not text.strip():
        return None
    try:
        matches = await vector_search(text, limit=8, threshold=0.70, include_archived=False)
    except EmbeddingError:
        return None
    feel_matches = [item for item in matches if str(item.get("type", "")) == "feel"]
    if len(feel_matches) < 2:
        return None
    existing_ids = [str(item["id"]) for item in feel_matches]
    payload = {
        "kind": "memory",
        "type": "pinned",
        "title": "反复出现的感受",
        "text": text.strip(),
        "reason": f"这份感受与 {len(existing_ids)} 条既有沉淀形成稳定主题，建议由你确认是否结晶。",
        "importance": 1.0,
        "valence": 0.5,
        "arousal": 0.6,
        "summary": "多次重复出现的关系感受",
        "domains": ["relationship"],
        "tags": ["feel", "crystallization"],
        "entities": [],
        "why_remembered": "这份感受跨越多次经历反复出现。",
        "source_message_ids": source_message_ids,
        "related_memory_ids": existing_ids,
    }
    marker = "feel-crystallization:" + ",".join(sorted(existing_ids))
    with db() as conn:
        duplicate = conn.execute(
            "SELECT id FROM pending_reviews WHERE status='pending' AND reason LIKE ? LIMIT 1",
            (f"%{marker}%",),
        ).fetchone()
        if duplicate:
            return None
        review_id = f"review_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO pending_reviews(id, kind, payload_json, reason, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                review_id,
                "memory",
                json.dumps(payload, ensure_ascii=False),
                f"{payload['reason']} [{marker}]",
                "pending",
                time.time(),
                time.time(),
            ),
        )
    return review_id
