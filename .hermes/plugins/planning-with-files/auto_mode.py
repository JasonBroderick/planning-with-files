from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import secrets
import tempfile


@dataclass
class ControlSnapshot:
    entries: dict[Path, bytes | None]


def _control_path(plan_dir: Path, name: str) -> Path:
    path = plan_dir / name
    if path.is_symlink():
        raise ValueError(f"PWF control file must not be a symlink: {path}")
    return path


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_write(path: Path, content: str) -> None:
    _atomic_write_bytes(path, content.encode("utf-8"))


def _plan_hash(plan: Path) -> str:
    digest = hashlib.sha256()
    with plan.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attestation_path(project_dir: Path, plan_dir: Path) -> Path:
    name = ".plan-attestation" if project_dir == plan_dir else ".attestation"
    return _control_path(plan_dir, name)


def _managed_paths(project_dir: Path, plan_dir: Path) -> list[Path]:
    return [
        _control_path(plan_dir, ".mode"),
        _control_path(plan_dir, ".nonce"),
        _control_path(plan_dir, ".stop_blocks"),
        _control_path(plan_dir, ".gate_last_ledger"),
        _attestation_path(project_dir, plan_dir),
    ]


def snapshot_controls(project_dir: Path, plan_dir: Path) -> ControlSnapshot:
    return ControlSnapshot(
        entries={path: path.read_bytes() if path.exists() else None for path in _managed_paths(project_dir, plan_dir)}
    )


def restore_controls(snapshot: ControlSnapshot) -> None:
    for path, content in snapshot.entries.items():
        if content is None:
            if path.exists():
                path.unlink()
        else:
            _atomic_write_bytes(path, content)


def disarm_autonomous(project_raw: Path, plan_raw: Path) -> dict[str, object]:
    project_dir = project_raw.resolve(strict=True)
    plan_dir = plan_raw.resolve(strict=True)
    try:
        plan_dir.relative_to(project_dir)
    except ValueError as exc:
        raise ValueError("active PWF plan must be inside the bound project") from exc

    removed: list[str] = []
    for name in (".mode", ".nonce", ".stop_blocks", ".gate_last_ledger"):
        path = _control_path(plan_dir, name)
        if path.exists():
            path.unlink()
            removed.append(name)
    return {
        "mode": "default",
        "removed": removed,
        "attestation_preserved": _attestation_path(project_dir, plan_dir).is_file(),
    }


def arm_autonomous(project_raw: Path, plan_raw: Path) -> dict[str, str]:
    project_dir = project_raw.resolve(strict=True)
    plan_dir = plan_raw.resolve(strict=True)
    try:
        plan_dir.relative_to(project_dir)
    except ValueError as exc:
        raise ValueError("active PWF plan must be inside the bound project") from exc

    plan = plan_dir / "task_plan.md"
    if not plan.is_file():
        raise ValueError(f"missing task plan: {plan}")
    if plan.is_symlink():
        raise ValueError("task_plan.md must not be a symlink")

    snapshot = snapshot_controls(project_dir, plan_dir)
    mode_path = _control_path(plan_dir, ".mode")
    nonce_path = _control_path(plan_dir, ".nonce")
    stop_path = _control_path(plan_dir, ".stop_blocks")
    stale_gate = _control_path(plan_dir, ".gate_last_ledger")
    attestation_path = _attestation_path(project_dir, plan_dir)
    nonce = secrets.token_hex(8)
    digest = _plan_hash(plan)

    try:
        _atomic_write(attestation_path, digest + "\n")
        if attestation_path.read_text(encoding="utf-8").strip() != digest:
            raise RuntimeError("PWF plan attestation verification failed")
        if _plan_hash(plan) != digest:
            raise RuntimeError("task_plan.md changed while autonomous mode was being armed")
        _atomic_write(stop_path, "0\n")
        _atomic_write(nonce_path, nonce + "\n")
        if stale_gate.exists():
            stale_gate.unlink()
        if _plan_hash(plan) != digest:
            raise RuntimeError("task_plan.md changed before autonomous mode activation")
        _atomic_write(mode_path, "autonomous\n")
    except Exception:
        restore_controls(snapshot)
        raise

    return {
        "mode": "autonomous",
        "nonce": nonce,
        "attestation": digest,
        "attestation_file": str(attestation_path),
        "plan": str(plan),
    }
