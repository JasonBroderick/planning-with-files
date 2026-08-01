import importlib
import json
import subprocess
from pathlib import Path

from .auto_mode import arm_autonomous, disarm_autonomous, restore_controls, snapshot_controls
from .hook_state import clear_reminders
from .paths import normalize_cwd, resolve_skill_dir
from .planning_files import ensure_planning_files, extract_current_phase, resolve_active_plan_dir, summarize_status
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


def _configured_goal_max_turns() -> int:
    goals_module = importlib.import_module("hermes_cli.goals")
    default_max_turns = int(goals_module.DEFAULT_MAX_TURNS)
    try:
        config_module = importlib.import_module("hermes_cli.config")
        configured = (config_module.load_config() or {}).get("goals") or {}
        return int(configured.get("max_turns", default_max_turns) or default_max_turns)
    except Exception:
        return default_max_turns


def _build_goal_manager(session_id: str, max_turns: int):
    goals_module = importlib.import_module("hermes_cli.goals")
    return goals_module.GoalManager(session_id=session_id, default_max_turns=max_turns)


def planning_with_files_start_auto(
    session_id: str = "",
    platform: str = "",
    max_turns: int = 0,
) -> str:
    del platform
    clean_session = str(session_id or "").strip()
    if not clean_session:
        return _error_result(ValueError("Hermes did not provide a session identity."))

    try:
        project_dir = _project_dir("", clean_session)
        plan_dir = resolve_active_plan_dir(project_dir)
        if plan_dir is None:
            raise ValueError("No active PWF plan found. Run /pwf first.")
        task_plan = plan_dir.joinpath("task_plan.md").read_text(encoding="utf-8")
        status = summarize_status(project_dir)
        counts = status.get("counts") or {}
        if counts.get("total", 0) and counts.get("complete", 0) >= counts.get("total", 0):
            raise ValueError("The bound PWF plan is already complete.")
        phase = extract_current_phase(task_plan)
        if phase == "No phase found":
            raise ValueError("The active task plan has no executable phase.")
        turn_budget = int(max_turns or _configured_goal_max_turns())
        if turn_budget < 1 or turn_budget > 1000:
            raise ValueError("max_turns must be between 1 and 1000")
    except (BindingError, BindingStoreError, OSError, ValueError) as exc:
        return _error_result(exc)

    snapshot = snapshot_controls(project_dir, plan_dir)
    try:
        armed = arm_autonomous(project_dir, plan_dir)
        goal = (
            f"Complete the active PWF phase '{phase}' in the bound project at {project_dir}. "
            "Read task_plan.md, findings.md, and progress.md before acting. Execute the phase's "
            "next concrete step, verify real results, keep the PWF files current, and continue "
            "until this phase is complete. Stop only if the phase is verified complete or a "
            "genuine external blocker requires user input."
        )
        manager = _build_goal_manager(clean_session, turn_budget)
        state = manager.set(goal, max_turns=turn_budget)
    except Exception as exc:
        try:
            restore_controls(snapshot)
        except Exception as rollback_exc:
            return _error_result(RuntimeError(f"auto-start failed: {exc}; rollback failed: {rollback_exc}"))
        return _error_result(exc)

    return json.dumps(
        {
            "ok": True,
            "goal_active": True,
            "project_dir": str(project_dir),
            "plan_dir": str(plan_dir),
            "phase": phase,
            "goal": goal,
            "max_turns": int(getattr(state, "max_turns", turn_budget)),
            "mode": armed["mode"],
            "nonce": armed["nonce"],
            "attestation": armed["attestation"],
            "attestation_file": armed["attestation_file"],
        },
        ensure_ascii=False,
    )


def planning_with_files_stop_auto(
    session_id: str = "",
    platform: str = "",
    reason: str = "PWF phase completed and verified",
) -> str:
    del platform
    clean_session = str(session_id or "").strip()
    if not clean_session:
        return _error_result(ValueError("Hermes did not provide a session identity."))
    try:
        project_dir = _project_dir("", clean_session)
        plan_dir = resolve_active_plan_dir(project_dir)
        if plan_dir is None:
            raise ValueError("No active PWF plan found. Run /pwf first.")
        result = disarm_autonomous(project_dir, plan_dir)
        manager = _build_goal_manager(clean_session, _configured_goal_max_turns())
        if manager.is_active():
            manager.mark_done(str(reason or "PWF phase completed and verified").strip())
    except (BindingError, BindingStoreError, OSError, RuntimeError, ValueError) as exc:
        return _error_result(exc)
    return json.dumps(
        {
            "ok": True,
            "project_dir": str(project_dir),
            "plan_dir": str(plan_dir),
            **result,
        },
        ensure_ascii=False,
    )


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
    plan_dir = resolve_active_plan_dir(project_dir) or project_dir.resolve()
    plan_file = plan_dir / "task_plan.md"
    completed = subprocess.run(
        ["sh", str(script), str(plan_file)],
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
