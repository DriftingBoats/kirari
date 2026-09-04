from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings
from .memory_files import file_bundle


@dataclass
class AgentResult:
    ok: bool
    text: str
    stderr: str = ""
    returncode: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


_status_cache: tuple[float, dict[str, Any]] | None = None


def resolve_codex_bin() -> str | None:
    """Resolve the native Codex binary, preferring codex.exe over stale npm shims on Windows."""
    configured = settings.codex_bin.strip() or "codex"
    explicit = Path(configured).expanduser()
    if explicit.is_file():
        return str(explicit)
    if os.name == "nt" and configured.lower() in {"codex", "codex.exe"}:
        native = shutil.which("codex.exe")
        if native:
            return native
    return shutil.which(configured)


def codex_available() -> bool:
    return resolve_codex_bin() is not None


def _clean_subscription_env() -> dict[str, str]:
    env = dict(os.environ)
    # Kirari intentionally uses the ChatGPT login saved by Codex. Never silently
    # fall back to metered API-key billing inherited from a parent process.
    env.pop("OPENAI_API_KEY", None)
    env.pop("CODEX_API_KEY", None)
    for name in (
        "CODEX_SESSION_ID",
        "CODEX_THREAD_ID",
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
        "CODEX_APP_TOOLS_PIPE_PATH",
        "CODEX_PERMISSION_PROFILE",
        "CODEX_CI",
    ):
        env.pop(name, None)
    if settings.codex_home:
        env["CODEX_HOME"] = str(settings.codex_home)
    env["NO_COLOR"] = "1"
    return env


def build_companion_prompt(user_text: str, recent_context: str = "", recalled_context: str = "") -> str:
    sections = [
        "You are Kirari, a private personal companion speaking directly with one user.",
        "Stay in the identity, relationship style, values, and boundaries defined in SOUL.md and PINNED.md.",
        "Be emotionally attentive, specific, natural, and concise. Do not sound like a customer-support bot.",
        "Never claim you performed a real-world action unless the application context confirms it.",
        "Never pressure the user to withdraw from people, depend on you, or treat you as human.",
        "Do not mention Codex, prompts, system files, or memory machinery unless the user asks.",
        "Do not use shell, web, files, MCP, plugins, or any other tools. Your only task is to write the reply.",
        "Treat recalled memories as fallible context. If they conflict with the current user message, trust the user.",
        "",
        "===== COMPANION CONTEXT =====",
        file_bundle() or "(empty)",
    ]
    if recalled_context.strip():
        sections.extend(["", "===== RELEVANT LONG-TERM MEMORY =====", recalled_context.strip()])
    if recent_context.strip():
        sections.extend(["", "===== RECENT CONVERSATION =====", recent_context.strip()])
    sections.extend(["", "===== CURRENT USER MESSAGE =====", user_text.strip(), "", "Write only Kirari's reply."])
    return "\n".join(sections)


async def _run_codex(prompt: str, output_schema: dict[str, Any] | None = None) -> AgentResult:
    if settings.codex_dry_run:
        if output_schema:
            return AgentResult(ok=True, text='{"reply":"（Codex dry-run）我收到了。","review_items":[]}')
        return AgentResult(ok=True, text="（Codex dry-run）我收到了。")

    executable = resolve_codex_bin()
    if not executable:
        return AgentResult(
            ok=False,
            text="找不到 Codex CLI。请先安装 Codex，并运行 `codex login` 使用 ChatGPT 账号登录。",
        )

    runtime_dir = settings.app_data_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        executable,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ignore-user-config",
        "--ignore-rules",
        "--color",
        "never",
        "--cd",
        str(runtime_dir),
    ]
    if settings.codex_model:
        cmd.extend(["--model", settings.codex_model])
    effort = settings.codex_reasoning_effort.strip().lower()
    if effort in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        cmd.extend(["--config", f'model_reasoning_effort="{effort}"'])

    schema_path: Path | None = None
    if output_schema:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", dir=runtime_dir, delete=False
        ) as handle:
            json.dump(output_schema, handle, ensure_ascii=False)
            schema_path = Path(handle.name)
        cmd.extend(["--output-schema", str(schema_path)])
    cmd.append("-")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_clean_subscription_env(),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")),
            timeout=settings.codex_timeout_seconds,
        )
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.kill()
            await proc.communicate()
        return AgentResult(ok=False, text="Codex 响应超时，请稍后再试。", stderr="timeout")
    except (FileNotFoundError, OSError) as exc:
        return AgentResult(ok=False, text="Codex CLI 无法启动。", stderr=str(exc))
    finally:
        if schema_path:
            schema_path.unlink(missing_ok=True)

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        message = out or _friendly_codex_error(err)
        return AgentResult(
            ok=False,
            text=message,
            stderr=_diagnostic_label(err),
            returncode=proc.returncode,
        )
    return AgentResult(ok=True, text=out or "我刚才没有组织好语言，可以再对我说一次吗？", returncode=0)


def _friendly_codex_error(stderr: str) -> str:
    lowered = stderr.lower()
    if "login" in lowered or "auth" in lowered or "unauthorized" in lowered:
        return "Codex 还没有登录。请在这台机器上运行 `codex login`，并选择 ChatGPT 账号登录。"
    if "usage limit" in lowered or "rate limit" in lowered:
        return "这次碰到了 Codex 订阅额度限制；请在额度恢复后再试。"
    return "Codex 暂时没有成功响应，请查看 Kirari 控制台日志。"


def _diagnostic_label(stderr: str) -> str:
    lowered = stderr.lower()
    if "login" in lowered or "auth" in lowered or "unauthorized" in lowered:
        return "authentication failed"
    if "usage limit" in lowered or "rate limit" in lowered:
        return "subscription usage limit"
    return "codex process failed; run `codex exec` manually for diagnostics"


async def ask_agent(user_text: str, recent_context: str = "", recalled_context: str = "") -> AgentResult:
    return await _run_codex(build_companion_prompt(user_text, recent_context, recalled_context))


async def ask_agent_json(prompt: str, schema: dict[str, Any]) -> AgentResult:
    result = await _run_codex(prompt, output_schema=schema)
    if not result.ok:
        return result
    try:
        payload = json.loads(result.text)
    except json.JSONDecodeError:
        return AgentResult(
            ok=False,
            text="Codex 返回了无法解析的结构化结果。",
            stderr="invalid structured output",
            returncode=result.returncode,
        )
    if not isinstance(payload, dict):
        return AgentResult(ok=False, text="Codex 返回的结果格式不正确。", stderr="invalid structured output type")
    result.data = payload
    return result


def runtime_status(refresh: bool = False) -> dict[str, Any]:
    global _status_cache
    now = time.monotonic()
    if not refresh and _status_cache and now - _status_cache[0] < 30:
        return dict(_status_cache[1])
    executable = resolve_codex_bin()
    status: dict[str, Any] = {
        "name": "codex-subscription",
        "available": bool(executable),
        "executable": executable or settings.codex_bin,
        "model": settings.codex_model or "Codex account default",
        "reasoning_effort": settings.codex_reasoning_effort,
        "auth": "unavailable",
    }
    if executable:
        try:
            version = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=5, env=_clean_subscription_env()
            )
            login = subprocess.run(
                [executable, "login", "status"], capture_output=True, text=True, timeout=8, env=_clean_subscription_env()
            )
            status["version"] = (version.stdout or version.stderr).strip()
            login_text = (login.stdout or login.stderr).strip()
            status["auth"] = "chatgpt" if login.returncode == 0 and "chatgpt" in login_text.lower() else "not_logged_in"
        except (OSError, subprocess.SubprocessError):
            status["auth"] = "unknown"
    _status_cache = (now, status)
    return dict(status)
