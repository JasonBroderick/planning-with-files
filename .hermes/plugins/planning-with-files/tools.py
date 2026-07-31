import json
import subprocess
from pathlib import Path

from .hook_state import clear_reminders
from .paths import normalize_cwd, resolve_skill_dir
from .planning_files import ensure_planning_files, summarize_status
from .project_bindings import (
    BindingError,
    BindingStoreError,
    bind_project,
    resolve_bound_project,
    unbind_project,
    validate_project_dir,
)


def _project_dir(cwd: str = "", session_id: str = "") -> Path:
    has_session = bool(str(session_id or "").strip())
    if str(cwd or "").strip():
        return validate_project_dir(cwd) if has_session else normalize_cwd(cwd)
    bound = resolve_bound_project(session_id)
    if bound is not None:
        return bound
    if has_session:
        raise BindingError("No PWF project is bound to this Hermes session. Bind a project or provide an allowed cwd.")
    return normalize_cwd()


def _error_result(error: Exception) -> str:
    return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)


def planning_with_files_bind_project(cwd: str, session_id: str = "") -> str:
    try:
        project_dir = bind_project(session_id, cwd)
    except (BindingError, BindingStoreError) as exc:
        return json.dumps({"ok": False, "bound": False, "error": str(exc)}, ensure_ascii=False)
    clear_reminders(session_id)
    result = summarize_status(project_dir)
    return json.dumps(
        {
            "ok": True,
            "bound": True,
            "project_dir": str(project_dir),
            "status": result,
        },
        ensure_ascii=False,
    )


def planning_with_files_unbind_project(session_id: str = "") -> str:
    if not str(session_id or "").strip():
        return json.dumps(
            {"ok": False, "unbound": False, "error": "Hermes did not provide a session identity."},
            ensure_ascii=False,
        )
    try:
        removed = unbind_project(session_id)
    except (BindingError, BindingStoreError) as exc:
        return json.dumps({"ok": False, "unbound": False, "error": str(exc)}, ensure_ascii=False)
    clear_reminders(session_id)
    return json.dumps({"ok": True, "unbound": removed}, ensure_ascii=False)


def planning_with_files_init(
    template: str = "default",
    cwd: str = "",
    session_id: str = "",
    platform: str = "",
) -> str:
    del platform
    try:
        project_dir = _project_dir(cwd, session_id)
        result = ensure_planning_files(project_dir, template=template)
    except (BindingError, BindingStoreError) as exc:
        return _error_result(exc)
    return json.dumps(result, ensure_ascii=False)


def planning_with_files_status(cwd: str = "", session_id: str = "", platform: str = "") -> str:
    del platform
    try:
        project_dir = _project_dir(cwd, session_id)
        result = summarize_status(project_dir)
    except (BindingError, BindingStoreError) as exc:
        return _error_result(exc)
    return json.dumps(result, ensure_ascii=False)


def planning_with_files_check_complete(
    cwd: str = "",
    session_id: str = "",
    platform: str = "",
) -> str:
    del platform
    try:
        project_dir = _project_dir(cwd, session_id)
    except (BindingError, BindingStoreError) as exc:
        return _error_result(exc)
    skill_root = resolve_skill_dir(project_dir)
    script = skill_root / "scripts" / "check-complete.sh"
    if not script.exists():
        return json.dumps(
            {"ok": False, "error": f"Missing script: {script}", "skill_root": str(skill_root), "complete": False},
            ensure_ascii=False,
        )
    completed = subprocess.run(
        ["sh", str(script)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_dir),
    )
    stdout = completed.stdout.strip()
    return json.dumps(
        {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": completed.stderr.strip(),
            "skill_root": str(skill_root),
            "complete": "ALL PHASES COMPLETE" in stdout,
        },
        ensure_ascii=False,
    )
