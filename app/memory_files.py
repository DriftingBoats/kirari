from __future__ import annotations

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


def ensure_memory_files() -> None:
    settings.memory_dir.mkdir(parents=True, exist_ok=True)
    for filename, initial in MEMORY_FILES.items():
        path = settings.memory_dir / filename
        if not path.exists():
            path.write_text(initial, encoding="utf-8")


def safe_filename(filename: str) -> str:
    if filename not in MEMORY_FILES:
        raise ValueError("unknown memory file")
    return filename


def read_memory_file(filename: str) -> str:
    ensure_memory_files()
    filename = safe_filename(filename)
    return (settings.memory_dir / filename).read_text(encoding="utf-8")


def write_memory_file(filename: str, content: str) -> None:
    ensure_memory_files()
    filename = safe_filename(filename)
    path = settings.memory_dir / filename
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    with db() as conn:
        conn.execute(
            "INSERT INTO file_versions(filename, content, created_at) VALUES(?,?,?)",
            (filename, previous, time.time()),
        )
    path.write_text(content, encoding="utf-8")


def append_memory_file(filename: str, heading: str, body: str) -> None:
    current = read_memory_file(filename)
    block = f"\n\n## {heading}\n\n{body.strip()}\n"
    write_memory_file(filename, current.rstrip() + block)


def file_bundle(max_chars: int = 12000) -> str:
    ensure_memory_files()
    parts: list[str] = []
    for filename in ["SOUL.md", "PINNED.md", "USER.md", "MEMORY.md", "FEEL.md"]:
        text = read_memory_file(filename).strip()
        if not text:
            continue
        parts.append(f"===== {filename} =====\n{text}")
    bundle = "\n\n".join(parts)
    if len(bundle) > max_chars:
        return bundle[:max_chars] + "\n\n[context truncated]"
    return bundle
