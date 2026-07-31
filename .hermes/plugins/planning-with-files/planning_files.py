import os
import re
import shutil
from pathlib import Path
from typing import Any

from .constants import PLANNING_FILES, PLAN_PREVIEW_LINES, PROGRESS_TAIL_LINES
from .paths import resolve_skill_dir


_VALID_PLAN_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]*$")


def _contained_plan_dir(project_dir: Path, candidate: Path) -> Path | None:
    try:
        root = project_dir.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_dir() and (resolved / "task_plan.md").is_file() else None


def resolve_active_plan_dir(project_dir: Path) -> Path | None:
    """Resolve the active plan with the same precedence as inject-plan.sh."""
    root = project_dir.resolve()
    planning_root = root / ".planning"

    plan_id = os.environ.get("PLAN_ID", "").strip()
    if _VALID_PLAN_ID.fullmatch(plan_id):
        resolved = _contained_plan_dir(root, planning_root / plan_id)
        if resolved is not None:
            return resolved

    active_file = planning_root / ".active_plan"
    if active_file.is_file():
        try:
            active_id = "".join(active_file.read_text(encoding="utf-8").split())
        except OSError:
            active_id = ""
        if _VALID_PLAN_ID.fullmatch(active_id):
            resolved = _contained_plan_dir(root, planning_root / active_id)
            if resolved is not None:
                return resolved

    newest: Path | None = None
    newest_mtime = -1.0
    if planning_root.is_dir():
        for candidate in sorted(planning_root.iterdir(), key=lambda path: path.name):
            if candidate.name.startswith(".") or not _VALID_PLAN_ID.fullmatch(candidate.name):
                continue
            resolved = _contained_plan_dir(root, candidate)
            if resolved is None:
                continue
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                mtime = 0.0
            if mtime > newest_mtime:
                newest = resolved
                newest_mtime = mtime
    if newest is not None:
        return newest
    return root if (root / "task_plan.md").is_file() else None


def tail_lines(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-limit:])


def head_lines(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:limit])


def ensure_planning_files(project_dir: Path, template: str = "default") -> dict[str, Any]:
    skill_root = resolve_skill_dir(project_dir)
    templates_dir = skill_root / "templates"
    plan_dir = resolve_active_plan_dir(project_dir) or project_dir.resolve()
    created: list[str] = []
    for name in PLANNING_FILES:
        dest = plan_dir / name
        if dest.exists():
            continue
        template_name = f"{name}"
        if template != "default":
            prefixed = templates_dir / f"{template}_{name}"
            source = prefixed if prefixed.exists() else templates_dir / template_name
        else:
            source = templates_dir / template_name
        if source.exists():
            shutil.copy2(source, dest)
        else:
            dest.write_text("", encoding="utf-8")
        created.append(name)
    return {
        "project_dir": str(project_dir.resolve()),
        "plan_dir": str(plan_dir),
        "created": created,
        "existing": [name for name in PLANNING_FILES if (plan_dir / name).exists()],
        "skill_root": str(skill_root),
    }


def phase_counts(task_plan: str) -> dict[str, int]:
    counts = {"complete": 0, "in_progress": 0, "pending": 0, "failed": 0, "total": 0}
    for line in task_plan.splitlines():
        normalized = line.strip().lower()
        if normalized.startswith("### phase"):
            counts["total"] += 1
        if "**status:**" not in normalized:
            continue
        if "complete" in normalized:
            counts["complete"] += 1
        elif "in_progress" in normalized:
            counts["in_progress"] += 1
        elif "failed" in normalized or "blocked" in normalized:
            counts["failed"] += 1
        elif "pending" in normalized:
            counts["pending"] += 1
    if counts["total"] == 0:
        for line in task_plan.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("|") and stripped.endswith("|")):
                continue
            cells = [cell.strip().lower() for cell in stripped.strip("|").split("|")]
            if len(cells) < 2 or cells[0] in {"phase", "error"} or set(cells[0]) == {"-"}:
                continue
            status = cells[1]
            if status in counts:
                counts[status] += 1
                counts["total"] += 1
        if counts["total"] == 0:
            for marker, key in (("[complete]", "complete"), ("[in_progress]", "in_progress"), ("[pending]", "pending")):
                counts[key] = task_plan.count(marker)
            counts["total"] = counts["complete"] + counts["in_progress"] + counts["pending"]
    return counts


def count_error_rows(task_plan: str) -> int:
    in_errors_section = False
    rows = 0
    for line in task_plan.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("## errors encountered"):
            in_errors_section = True
            continue
        if in_errors_section and stripped.startswith("## "):
            break
        if not in_errors_section:
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = [cell.strip().lower() for cell in stripped.strip("|").split("|")]
        if not cells or cells[0] == "error" or set(cells[0]) == {"-"}:
            continue
        rows += 1
    return rows


def extract_current_phase(task_plan: str) -> str:
    lines = task_plan.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == "## current phase":
            for next_line in lines[idx + 1 :]:
                candidate = next_line.strip()
                if not candidate or candidate.startswith("<!--"):
                    continue
                if candidate.endswith("-->") or candidate.startswith("WHAT:") or candidate.startswith("WHY:") or candidate.startswith("EXAMPLE:"):
                    continue
                return candidate
            return stripped
    current_phase_name = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### Phase"):
            current_phase_name = stripped
        if "**status:**" in stripped.lower() and "in_progress" in stripped.lower() and current_phase_name:
            return current_phase_name
    if current_phase_name is None:
        for line in lines:
            stripped = line.strip()
            if not (stripped.startswith("|") and stripped.endswith("|")):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) < 2 or cells[0].lower() == "phase" or set(cells[0]) == {"-"}:
                continue
            if cells[1].lower() == "in_progress":
                return cells[0]
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### Phase"):
            return stripped
    return "No phase found"


def summarize_status(project_dir: Path) -> dict[str, Any]:
    plan_dir = resolve_active_plan_dir(project_dir)
    effective_dir = plan_dir or project_dir.resolve()
    task_plan_path = effective_dir / "task_plan.md"
    findings_path = effective_dir / "findings.md"
    progress_path = effective_dir / "progress.md"
    if not task_plan_path.exists():
        return {
            "exists": False,
            "project_dir": str(project_dir.resolve()),
            "plan_dir": None,
            "message": "No planning files found. Run planning_with_files_init first.",
            "files": {
                "task_plan.md": task_plan_path.exists(),
                "findings.md": findings_path.exists(),
                "progress.md": progress_path.exists(),
            },
        }
    task_plan = task_plan_path.read_text(encoding="utf-8")
    counts = phase_counts(task_plan)
    return {
        "exists": True,
        "project_dir": str(project_dir.resolve()),
        "plan_dir": str(effective_dir),
        "current_phase": extract_current_phase(task_plan),
        "counts": counts,
        "files": {
            "task_plan.md": task_plan_path.exists(),
            "findings.md": findings_path.exists(),
            "progress.md": progress_path.exists(),
        },
        "recent_progress": tail_lines(progress_path, PROGRESS_TAIL_LINES),
        "plan_preview": head_lines(task_plan_path, PLAN_PREVIEW_LINES),
        "errors_logged": count_error_rows(task_plan),
    }
