from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .constants import PROGRESS_TAIL_LINES, READ_PREVIEW_LINES
from .hook_state import add_reminder, pop_reminders
from .paths import normalize_cwd, resolve_skill_dir
from .planning_files import head_lines, tail_lines
from .project_bindings import resolve_bound_project

logger = logging.getLogger(__name__)
_SMART_INJECT_TIMEOUT_SECONDS = 5
_DEFAULT_MAX_CONTEXT_BYTES = 65_536
_MIN_MAX_CONTEXT_BYTES = 4_096
_MAX_MAX_CONTEXT_BYTES = 1_048_576


def _legacy_context(project_dir: Path) -> str:
    task_plan = project_dir / "task_plan.md"
    if not task_plan.exists():
        return ""
    parts = ["[planning-with-files] ACTIVE PLAN: current state:"]
    head = head_lines(task_plan, READ_PREVIEW_LINES)
    if head:
        parts.append(head)
    progress = tail_lines(project_dir / "progress.md", PROGRESS_TAIL_LINES)
    if progress:
        parts.append("=== recent progress ===")
        parts.append(progress)
    findings = project_dir / "findings.md"
    if findings.exists():
        parts.append("[planning-with-files] Read findings.md for research context. Continue from the current phase.")
    return "\n\n".join(parts)


def _max_context_bytes() -> int:
    raw = os.environ.get("PWF_HERMES_MAX_CONTEXT_BYTES", "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MAX_CONTEXT_BYTES
    except ValueError:
        value = _DEFAULT_MAX_CONTEXT_BYTES
    return max(_MIN_MAX_CONTEXT_BYTES, min(value, _MAX_MAX_CONTEXT_BYTES))


def _bounded_context(stream, limit: int) -> str:
    stream.seek(0)
    payload = stream.read(limit + 1)
    truncated = len(payload) > limit
    context = payload[:limit].decode("utf-8", errors="replace").rstrip()
    if truncated:
        nonce_begin = re.search(r"===BEGIN-PLAN-DATA-([A-Za-z0-9]+)===", context)
        if nonce_begin:
            end_delimiter = "===END-PLAN-DATA-%s===" % nonce_begin.group(1)
            if end_delimiter not in context:
                context += "\n" + end_delimiter
        elif "===BEGIN PLAN DATA===" in context and "===END PLAN DATA===" not in context:
            context += "\n===END PLAN DATA==="
        context += "\n[planning-with-files] CONTEXT TRUNCATED at %d bytes." % limit
    return context


def _smart_context(project_dir: Path) -> str | None:
    """Return smart context, or None only when the helper is unavailable."""
    skill_root = resolve_skill_dir(project_dir)
    script = skill_root / "scripts" / "inject-plan.sh"
    shell = shutil.which("sh")
    if not script.is_file() or shell is None:
        return None
    env = os.environ.copy()
    env["PWF_INJECT"] = "smart"
    try:
        with tempfile.TemporaryFile(mode="w+b") as output:
            completed = subprocess.run(
                [shell, str(script), "--context=userprompt"],
                cwd=str(project_dir),
                env=env,
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=_SMART_INJECT_TIMEOUT_SECONDS,
            )
            if completed.returncode != 0:
                logger.debug("planning-with-files smart injection returned nonzero status")
                return ""
            context = _bounded_context(output, _max_context_bytes())
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("planning-with-files smart injection failed closed: %s", type(exc).__name__)
        return ""
    if not _findings_exists(project_dir):
        context = "\n".join(
            line
            for line in context.splitlines()
            if not line.startswith("[planning-with-files] Read findings.md for research context.")
        ).strip()
    return context


def _findings_exists(project_dir: Path) -> bool:
    if (project_dir / "findings.md").exists():
        return True
    planning_dir = project_dir / ".planning"
    return planning_dir.is_dir() and any(planning_dir.glob("*/findings.md"))


def _has_planning_state(project_dir: Path) -> bool:
    if (project_dir / "task_plan.md").exists():
        return True
    planning_dir = project_dir / ".planning"
    return planning_dir.is_dir() and any(planning_dir.glob("*/task_plan.md"))


def build_user_prompt_context(project_dir: Path) -> str:
    smart = _smart_context(project_dir)
    if smart is not None:
        return smart
    return _legacy_context(project_dir)


def _project_for_pre_llm(session_id: str, platform: str) -> Path | None:
    bound = resolve_bound_project(session_id)
    if bound is not None:
        return bound
    platform_name = str(platform or "").strip().lower()
    if str(session_id or "").strip() and platform_name not in {"", "cli"}:
        return None
    return normalize_cwd()


def _project_for_post_tool(session_id: str, platform: str) -> Path | None:
    del platform
    bound = resolve_bound_project(session_id)
    if bound is not None:
        return bound
    return normalize_cwd()


def pre_llm_call(**kwargs: Any) -> dict[str, str] | None:
    user_message = str(kwargs.get("user_message", ""))
    session_id = str(kwargs.get("session_id") or kwargs.get("task_id") or "")
    platform = str(kwargs.get("platform", ""))
    reminder_messages = pop_reminders(session_id)
    project_dir = _project_for_pre_llm(session_id, platform)
    if project_dir is None:
        return None
    if not _has_planning_state(project_dir):
        return {"context": "\n".join(reminder_messages)} if reminder_messages else None
    context = build_user_prompt_context(project_dir)
    parts: list[str] = []
    if reminder_messages:
        parts.append("\n".join(reminder_messages))
    if context:
        parts.append(context)
    if not user_message.strip() and not kwargs.get("is_first_turn") and not reminder_messages:
        return None
    if not parts:
        return None
    return {"context": "\n\n".join(parts)}


def post_tool_call(**kwargs: Any) -> None:
    tool_name = str(kwargs.get("tool_name", ""))
    args = kwargs.get("args") or {}
    if tool_name == "write_file":
        if not args.get("path") or "content" not in args:
            return None
    elif tool_name == "patch":
        has_patch_payload = bool(args.get("patch"))
        has_replace_payload = bool(args.get("path")) and "old_string" in args and "new_string" in args
        if not (has_patch_payload or has_replace_payload):
            return None
    else:
        return None
    session_id = str(kwargs.get("session_id") or kwargs.get("task_id") or "")
    platform = str(kwargs.get("platform", ""))
    project_dir = _project_for_post_tool(session_id, platform)
    if project_dir is None or not _has_planning_state(project_dir):
        return None
    message = "[planning-with-files] Update progress.md with what you just did. If a phase is now complete, update task_plan.md status."
    add_reminder(session_id, message)
    return None
