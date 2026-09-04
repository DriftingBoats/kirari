from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import settings
from .db import db, rows_to_dicts, upsert_memory_item


BUCKET_STATES = ("active", "archive", "tombstone")
_SAFE_PART = re.compile(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]+")


def bucket_root() -> Path:
    return settings.memory_dir / "buckets"


def ensure_bucket_dirs() -> None:
    for state in BUCKET_STATES:
        (bucket_root() / state).mkdir(parents=True, exist_ok=True)


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _safe_part(value: str, fallback: str) -> str:
    cleaned = _SAFE_PART.sub("-", value.strip()).strip("-")
    return cleaned[:64] or fallback


def _state_for(item: dict[str, Any]) -> str:
    if int(item.get("tombstoned", 0)):
        return "tombstone"
    if int(item.get("archived", 0)):
        return "archive"
    return "active"


def _domain_for(item: dict[str, Any]) -> str:
    domains = _json_value(item.get("domains_json", item.get("domains", [])), [])
    first = str(domains[0]) if isinstance(domains, list) and domains else "general"
    return _safe_part(first, "general")


def _bucket_path(item: dict[str, Any]) -> Path:
    memory_id = _safe_part(str(item["id"]), "memory")
    return bucket_root() / _state_for(item) / _domain_for(item) / f"{memory_id}.md"


def find_bucket_paths(memory_id: str) -> list[Path]:
    safe_id = _safe_part(memory_id, "memory")
    ensure_bucket_dirs()
    return list(bucket_root().glob(f"*/**/{safe_id}.md"))


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item["id"]),
        "type": str(item.get("type", "event")),
        "state": _state_for(item),
        "title": str(item.get("title", "")),
        "summary": str(item.get("summary", "")),
        "domains": _json_value(item.get("domains_json", item.get("domains", [])), []),
        "tags": _json_value(item.get("tags_json", item.get("tags", [])), []),
        "entities": _json_value(item.get("entities_json", item.get("entities", [])), []),
        "importance": float(item.get("importance", 0.5)),
        "valence": float(item.get("valence", 0.5)),
        "arousal": float(item.get("arousal", item.get("emotional_weight", 0.3))),
        "activation_count": float(item.get("activation_count", 0)),
        "last_active": float(item.get("last_active") or item.get("updated_at") or time.time()),
        "pinned": bool(item.get("pinned", 0)),
        "resolved": bool(item.get("resolved", 0)),
        "digested": bool(item.get("digested", 0)),
        "approved": bool(item.get("approved", 1)),
        "why_remembered": str(item.get("why_remembered", "")),
        "source_message_ids": _json_value(item.get("source_message_ids", []), []),
        "footprints": _json_value(item.get("footprints_json", item.get("footprints", [])), []),
        "lineage": _json_value(item.get("lineage_json", item.get("lineage", {})), {}),
        "created_at": float(item.get("created_at") or time.time()),
        "updated_at": float(item.get("updated_at") or time.time()),
        "archived_at": item.get("archived_at"),
        "deleted_at": item.get("deleted_at"),
    }


def _serialise(item: dict[str, Any]) -> str:
    frontmatter = yaml.safe_dump(
        _metadata(item), allow_unicode=True, sort_keys=False, width=1000
    ).strip()
    return f"---\n{frontmatter}\n---\n\n{str(item.get('text', '')).strip()}\n"


def write_bucket(item: dict[str, Any]) -> Path:
    """Atomically publish the canonical memory before updating projections."""
    ensure_bucket_dirs()
    target = _bucket_path(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    contents = _serialise(item)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, prefix=f".{target.stem}-", suffix=".tmp", delete=False
    ) as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, target)
    for old_path in find_bucket_paths(str(item["id"])):
        if old_path != target:
            old_path.unlink(missing_ok=True)
    return target


def read_bucket(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(f"missing frontmatter: {path}")
    try:
        header, text = raw[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError(f"invalid frontmatter: {path}") from exc
    meta = yaml.safe_load(header) or {}
    if not isinstance(meta, dict) or not meta.get("id"):
        raise ValueError(f"invalid bucket metadata: {path}")
    state = str(meta.get("state") or path.parts[-3])
    item = dict(meta)
    item["text"] = text.strip()
    item["archived"] = 1 if state in {"archive", "tombstone"} else 0
    item["tombstoned"] = 1 if state == "tombstone" else 0
    item["pinned"] = int(bool(meta.get("pinned")))
    item["resolved"] = int(bool(meta.get("resolved")))
    item["digested"] = int(bool(meta.get("digested")))
    item["approved"] = int(bool(meta.get("approved", True)))
    item["domains"] = meta.get("domains") or []
    item["tags"] = meta.get("tags") or []
    item["entities"] = meta.get("entities") or []
    item["footprints"] = meta.get("footprints") or []
    item["lineage"] = meta.get("lineage") or {}
    return item


def iter_buckets(states: Iterable[str] = BUCKET_STATES) -> Iterable[tuple[Path, dict[str, Any]]]:
    ensure_bucket_dirs()
    for state in states:
        if state not in BUCKET_STATES:
            continue
        for path in (bucket_root() / state).glob("**/*.md"):
            try:
                yield path, read_bucket(path)
            except (OSError, ValueError, yaml.YAMLError):
                continue


def append_footprint(
    item: dict[str, Any], action: str, *, detail: str = "", related_id: str = ""
) -> dict[str, Any]:
    item = dict(item)
    footprints = list(_json_value(item.get("footprints_json", item.get("footprints", [])), []))
    footprint: dict[str, Any] = {"at": time.time(), "action": action}
    if detail:
        footprint["detail"] = detail
    if related_id:
        footprint["related_id"] = related_id
    footprints.append(footprint)
    item["footprints"] = footprints[-100:]
    item["footprints_json"] = item["footprints"]
    return item


def persist_bucket(item: dict[str, Any], action: str, *, detail: str = "", related_id: str = "") -> dict[str, Any]:
    now = time.time()
    item = dict(item)
    item.setdefault("created_at", now)
    item["updated_at"] = now
    item = append_footprint(item, action, detail=detail, related_id=related_id)
    write_bucket(item)
    upsert_memory_item(item)
    return item


def reconcile_memory_store() -> dict[str, int]:
    """Make bucket files canonical while safely migrating legacy DB-only rows."""
    ensure_bucket_dirs()
    projected = 0
    exported = 0
    bucket_ids: set[str] = set()
    for _, item in iter_buckets():
        bucket_ids.add(str(item["id"]))
        upsert_memory_item(item)
        projected += 1
    with db() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM memory_items").fetchall())
    for item in rows:
        if str(item["id"]) in bucket_ids:
            continue
        legacy = append_footprint(item, "migrated", detail="legacy SQLite record")
        write_bucket(legacy)
        upsert_memory_item(legacy)
        exported += 1
    return {"projected": projected, "exported": exported}
