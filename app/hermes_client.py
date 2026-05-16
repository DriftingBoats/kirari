from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass

from .config import settings
from .memory_files import file_bundle


@dataclass
class HermesResult:
    ok: bool
    text: str
    stderr: str = ""
    returncode: int | None = None


def hermes_available() -> bool:
    return shutil.which(settings.hermes_bin) is not None


def build_companion_prompt(user_text: str, recent_context: str = "", recalled_context: str = "") -> str:
    system_context = file_bundle()
    sections = [
        "You are responding inside a Telegram private chat with the user.",
        "Use Hermes memory normally, but also obey the companion context below.",
        "Do not mention system files unless the user asks. Keep the reply intimate, natural, and grounded.",
        "Do not invent calendar/reminder actions; if the user asks for one, phrase it clearly so the app can extract it.",
        "",
        "===== COMPANION CONTEXT =====",
        system_context or "(empty)",
    ]
    if recalled_context.strip():
        sections.extend(["", "===== RECALLED LOCAL CONTEXT =====", recalled_context.strip()])
    if recent_context.strip():
        sections.extend(["", "===== RECENT TELEGRAM CONTEXT =====", recent_context.strip()])
    sections.extend(["", "===== USER MESSAGE =====", user_text.strip(), "", "Reply:"])
    return "\n".join(sections)


async def ask_hermes(user_text: str, recent_context: str = "", recalled_context: str = "") -> HermesResult:
    prompt = build_companion_prompt(user_text, recent_context, recalled_context)
    if settings.hermes_dry_run:
        return HermesResult(ok=True, text=f"（Hermes dry-run）我收到了：{user_text}")
    if not hermes_available():
        return HermesResult(
            ok=False,
            text="Hermes is not installed or not on PATH. Install Hermes and set HERMES_BIN if needed.",
        )

    cmd = [settings.hermes_bin, "chat", "-q", prompt]
    if settings.hermes_provider:
        cmd.extend(["--provider", settings.hermes_provider])
    if settings.hermes_model:
        cmd.extend(["--model", settings.hermes_model])

    env = dict(os.environ)
    env["HERMES_HOME"] = str(settings.hermes_home)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=settings.hermes_timeout_seconds,
        )
    except asyncio.TimeoutError:
        return HermesResult(ok=False, text="Hermes timed out.", stderr="timeout")
    except FileNotFoundError:
        return HermesResult(ok=False, text="Hermes executable not found.")

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        return HermesResult(ok=False, text=out or err or "Hermes failed.", stderr=err, returncode=proc.returncode)
    return HermesResult(ok=True, text=out or "（Hermes 没有返回内容）", stderr=err, returncode=proc.returncode)
