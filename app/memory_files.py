from __future__ import annotations

import re
import time
from pathlib import Path

from .config import settings
from .db import db

MEMORY_FILES = {
    "SOUL.md": "# SOUL\n\nDefine who the companion is, how they love, and what must stay stable.\n",
    "USER.md": "# USER\n\nStable facts about the user.\n",
    "MEMORY.md": "# MEMORY\n\nLong-term factual memories.\n",
    "FEEL.md": "# FEEL\n\nFirst-person relationship sediment. These are role memories, not objective facts.\n",
    "DREAM.md": "# DREAM\n\nDaily and stage-based digestion logs.\n",
    "PINNED.md": "# PINNED\n\nPromises, boundaries, and hard rules. User-edited only.\n",
    "BOARD.md": "# BOARD\n\nCurated board messages.\n",
}

READ_ONLY_FOR_AI = {"SOUL.md", "PINNED.md"}
CONTEXT_SOURCES = ["PINNED.md", "USER.md", "MEMORY.md", "FEEL.md", "DREAM.md", "BOARD.md"]


def memory_file_path(filename: str) -> Path:
    filename = safe_filename(filename)
    return settings.memory_dir / filename


def ensure_memory_files() -> None:
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    for filename, initial in MEMORY_FILES.items():
        path = memory_file_path(filename)
        if not path.exists():
            path.write_text(initial, encoding="utf-8")


def safe_filename(filename: str) -> str:
    if filename not in MEMORY_FILES:
        raise ValueError("unknown memory file")
    return filename


def read_memory_file(filename: str) -> str:
    ensure_memory_files()
    filename = safe_filename(filename)
    return memory_file_path(filename).read_text(encoding="utf-8")


def write_memory_file(filename: str, content: str) -> None:
    ensure_memory_files()
    filename = safe_filename(filename)
    path = memory_file_path(filename)
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    with db() as conn:
        conn.execute(
            "INSERT INTO file_versions(filename, content, created_at) VALUES(?,?,?)",
            (filename, previous, time.time()),
        )
    path.write_text(content, encoding="utf-8")


def list_file_versions(filename: str, limit: int = 20) -> list[dict]:
    filename = safe_filename(filename)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, filename, length(content) AS size, created_at
            FROM file_versions
            WHERE filename=?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (filename, min(max(limit, 1), 100)),
        ).fetchall()
    return [dict(row) for row in rows]


def restore_file_version(filename: str, version_id: int) -> None:
    filename = safe_filename(filename)
    with db() as conn:
        row = conn.execute(
            "SELECT content FROM file_versions WHERE id=? AND filename=?",
            (version_id, filename),
        ).fetchone()
    if not row:
        raise ValueError("unknown file version")
    write_memory_file(filename, row["content"])


def append_memory_file(filename: str, heading: str, body: str) -> None:
    current = read_memory_file(filename)
    block = f"\n\n## {heading}\n\n{body.strip()}\n"
    write_memory_file(filename, current.rstrip() + block)


def upsert_memory_block(memory_id: str, heading: str, body: str) -> None:
    """Keep DB-backed memory rows removable without touching hand-written Markdown."""
    safe_heading = " ".join(str(heading).splitlines()).strip() or "Memory"
    start = f"<!-- kirari-memory:{memory_id} -->"
    end = f"<!-- /kirari-memory:{memory_id} -->"
    block = f"{start}\n## {safe_heading}\n\n{body.strip()}\n{end}"
    current = read_memory_file("MEMORY.md")
    pattern = re.compile(
        rf"(?:\n\n)?{re.escape(start)}[\s\S]*?{re.escape(end)}(?:\n)?",
        re.MULTILINE,
    )
    if pattern.search(current):
        updated = pattern.sub("\n\n" + block + "\n", current, count=1)
    else:
        updated = current.rstrip() + "\n\n" + block + "\n"
    write_memory_file("MEMORY.md", updated)


def remove_memory_block(memory_id: str) -> bool:
    start = f"<!-- kirari-memory:{memory_id} -->"
    end = f"<!-- /kirari-memory:{memory_id} -->"
    current = read_memory_file("MEMORY.md")
    pattern = re.compile(
        rf"(?:\n\n)?{re.escape(start)}[\s\S]*?{re.escape(end)}(?:\n)?",
        re.MULTILINE,
    )
    updated, count = pattern.subn("\n", current, count=1)
    if count:
        write_memory_file("MEMORY.md", updated.rstrip() + "\n")
    return bool(count)


def file_bundle(max_chars: int = 12000) -> str:
    ensure_memory_files()
    parts: list[str] = []
    for filename in ["SOUL.md", *CONTEXT_SOURCES]:
        text = read_memory_file(filename).strip()
        if filename == "MEMORY.md":
            # Legacy generated blocks now live in canonical per-memory bucket
            # files and are supplied only through retrieval. Preserve any
            # hand-written text around them.
            text = re.sub(
                r"(?:\n\n)?<!-- kirari-memory:[^>]+ -->[\s\S]*?<!-- /kirari-memory:[^>]+ -->(?:\n)?",
                "\n",
                text,
            ).strip()
        if not text:
            continue
        parts.append(f"===== {filename} =====\n{text}")
    bundle = "\n\n".join(parts)
    if len(bundle) > max_chars:
        return bundle[:max_chars] + "\n\n[context truncated]"
    return bundle
