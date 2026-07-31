from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

_STATE_ENV = "PWF_HERMES_STATE_DIR"
_ROOTS_ENV = "PWF_HERMES_PROJECT_ROOTS"
_ROOTS_FILE_ENV = "PWF_HERMES_PROJECT_ROOTS_FILE"
_DB_NAME = "bindings.sqlite3"
_SCHEMA_VERSION = 1
_DB_LOCK = threading.RLock()
_INITIALIZED_DATABASES: set[Path] = set()


class BindingError(ValueError):
    """Raised when a session or project cannot be bound safely."""


class BindingStoreError(RuntimeError):
    """Raised when the private binding store cannot complete an operation."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME", "").strip()
    return (Path(configured).expanduser() if configured else Path.home() / ".hermes").resolve()


def _state_dir() -> Path:
    explicit = os.environ.get(_STATE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (_hermes_home() / "state" / "planning-with-files").resolve()


def _configured_roots_file() -> Path:
    explicit = os.environ.get(_ROOTS_FILE_ENV, "").strip()
    return Path(explicit).expanduser().resolve() if explicit else _state_dir() / "project-roots"


def _roots_from_file() -> list[str]:
    roots_file = _configured_roots_file()
    if not roots_file.is_file():
        return []
    try:
        lines = roots_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _allowed_roots() -> list[Path]:
    configured = os.environ.get(_ROOTS_ENV, "").strip()
    candidates: Iterable[str | Path]
    if configured:
        candidates = [part for part in configured.split(os.pathsep) if part.strip()]
    else:
        file_roots = _roots_from_file()
        candidates = file_roots if file_roots else [Path.cwd(), _hermes_home()]

    roots: list[Path] = []
    seen: set[Path] = set()
    for value in candidates:
        try:
            root = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if not root.is_dir() or root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


def _ensure_private_path(path: Path, mode: int) -> None:
    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        pass


def _database_path() -> Path:
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    _ensure_private_path(state_dir, 0o700)
    return state_dir / _DB_NAME


def _connect() -> sqlite3.Connection:
    db_path = _database_path()
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(str(db_path), timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        with _DB_LOCK:
            if db_path not in _INITIALIZED_DATABASES:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if version > _SCHEMA_VERSION:
                    raise BindingStoreError("The PWF binding database was created by a newer plugin version.")
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = NORMAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bindings (
                        session_key TEXT PRIMARY KEY,
                        root_key TEXT NOT NULL,
                        project_rel TEXT NOT NULL
                    )
                    """
                )
                if version < _SCHEMA_VERSION:
                    connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                connection.commit()
                _INITIALIZED_DATABASES.add(db_path)
        _ensure_private_path(db_path, 0o600)
        return connection
    except BindingStoreError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise BindingStoreError("The PWF binding database is unavailable.") from exc


def _validated_session_key(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value:
        raise BindingError("Hermes did not provide a session identity; project binding was not changed.")
    return _digest(value)


def _locate_project(project_dir: str | Path) -> tuple[Path, str, str]:
    value = str(project_dir or "").strip()
    if not value:
        raise BindingError("A project directory is required.")
    try:
        candidate = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise BindingError("The project directory does not exist or cannot be resolved.") from exc
    if not candidate.is_dir():
        raise BindingError("The project path must be a directory.")

    for root in _allowed_roots():
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        return candidate, _digest(str(root)), relative.as_posix() or "."
    raise BindingError(
        "The project directory is outside the configured PWF_HERMES_PROJECT_ROOTS boundary."
    )


def validate_project_dir(project_dir: str | Path) -> Path:
    candidate, _root_key, _project_rel = _locate_project(project_dir)
    return candidate


def bind_project(session_id: str, project_dir: str | Path) -> Path:
    session_key = _validated_session_key(session_id)
    candidate, root_key, project_rel = _locate_project(project_dir)
    with _DB_LOCK:
        connection = _connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO bindings(session_key, root_key, project_rel)
                VALUES (?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    root_key = excluded.root_key,
                    project_rel = excluded.project_rel
                """,
                (session_key, root_key, project_rel),
            )
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise BindingStoreError("The PWF project binding could not be saved.") from exc
        finally:
            connection.close()
    return candidate


def resolve_bound_project(session_id: str) -> Path | None:
    try:
        session_key = _validated_session_key(session_id)
    except BindingError:
        return None
    try:
        with _DB_LOCK:
            connection = _connect()
            try:
                row = connection.execute(
                    "SELECT root_key, project_rel FROM bindings WHERE session_key = ?",
                    (session_key,),
                ).fetchone()
            finally:
                connection.close()
    except (sqlite3.Error, BindingStoreError):
        return None
    if row is None:
        return None

    stored_root_key, project_rel = str(row[0]), str(row[1])
    for root in _allowed_roots():
        if _digest(str(root)) != stored_root_key:
            continue
        try:
            candidate = (root / project_rel).resolve(strict=True)
            candidate.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            return None
        return candidate if candidate.is_dir() else None
    return None


def unbind_project(session_id: str) -> bool:
    session_key = _validated_session_key(session_id)
    with _DB_LOCK:
        connection = _connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "DELETE FROM bindings WHERE session_key = ?",
                (session_key,),
            )
            connection.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as exc:
            connection.rollback()
            raise BindingStoreError("The PWF project binding could not be removed.") from exc
        finally:
            connection.close()


def reset_store_cache() -> None:
    """Reset process-local schema state for tests and controlled reloads."""
    with _DB_LOCK:
        _INITIALIZED_DATABASES.clear()
