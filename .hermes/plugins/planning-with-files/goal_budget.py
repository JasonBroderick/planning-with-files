from __future__ import annotations

import importlib
import logging
import re
from typing import Any

from .auto_mode import disarm_autonomous
from .planning_files import resolve_active_plan_dir
from .project_bindings import resolve_bound_project

logger = logging.getLogger(__name__)
_BRIDGE_SENTINEL = "_pwf_goal_budget_bridge_installed"


def _is_budget_exhaustion(decision: Any) -> bool:
    if not isinstance(decision, dict):
        return False
    message = str(decision.get("message") or "").lower()
    return (
        decision.get("status") == "paused"
        and decision.get("should_continue") is False
        and decision.get("verdict") == "continue"
        and "turns used" in message
    )


def _disarm_exhausted_pwf(session_id: str) -> bool:
    project_dir = resolve_bound_project(session_id)
    if project_dir is None:
        return False
    plan_dir = resolve_active_plan_dir(project_dir)
    if plan_dir is None:
        return False
    mode_path = plan_dir / ".mode"
    if not mode_path.is_file() or mode_path.read_text(encoding="utf-8").strip() != "autonomous":
        return False
    disarm_autonomous(project_dir, plan_dir)
    return True


def _pwf_budget_message(original_message: str) -> str:
    match = re.search(r"(\d+/\d+ turns used)", original_message)
    budget = f" ({match.group(1)})" if match else ""
    return (
        f"⏸ PWF auto paused: turn budget exhausted{budget}. "
        "Autonomous controls were disarmed and the incomplete phase was preserved. "
        "Run /pwf-auto to continue this phase with a fresh bounded budget."
    )


def install_goal_budget_bridge(goal_manager_cls: Any = None) -> bool:
    if goal_manager_cls is None:
        goal_manager_cls = importlib.import_module("hermes_cli.goals").GoalManager

    if getattr(goal_manager_cls, _BRIDGE_SENTINEL, False):
        return True

    original = goal_manager_cls.evaluate_after_turn

    def evaluate_after_turn(self, *args: Any, **kwargs: Any):
        decision = original(self, *args, **kwargs)
        if not _is_budget_exhaustion(decision):
            return decision
        try:
            if _disarm_exhausted_pwf(str(getattr(self, "session_id", "") or "")):
                decision = dict(decision)
                decision["message"] = _pwf_budget_message(str(decision.get("message") or ""))
        except Exception as exc:
            logger.warning("PWF goal-budget cleanup failed open: %s", exc)
        return decision

    goal_manager_cls.evaluate_after_turn = evaluate_after_turn
    setattr(goal_manager_cls, _BRIDGE_SENTINEL, True)
    return True
