#!/usr/bin/env python3
"""Shared helpers for repository maintenance scripts.

Responsibilities
----------------
- Resolve repository-local executables deterministically.
- Run subprocesses with predictable working directories and environments.
- Provide small formatting helpers used by benchmark wrappers.

Design principles
-----------------
Scripts should fail fast with explicit messages and avoid shell-dependent
control flow.

Architectural role
------------------
This module belongs to the developer tooling layer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from types import TracebackType

REPO_ROOT = Path(__file__).resolve().parents[1]


class RepoConfigRestore:
    """Context manager that restores repo-local Codira configs on exit."""

    def __init__(self, repos: Sequence[Path], backup_root: Path) -> None:
        """
        Initialize the repository config restorer.

        Parameters
        ----------
        repos : collections.abc.Sequence[pathlib.Path]
            Repository roots whose ``.codira/config.toml`` files are managed.
        backup_root : pathlib.Path
            Directory used for backup state.

        Returns
        -------
        None
        """

        self.repos = tuple(repos)
        self.backup_root = backup_root

    def __enter__(self) -> RepoConfigRestore:
        """
        Back up configured repositories.

        Parameters
        ----------
        None

        Returns
        -------
        RepoConfigRestore
            This restorer.
        """

        self.backup_root.mkdir(parents=True, exist_ok=True)
        for repo in self.repos:
            safe = safe_slug(str(repo))
            state_dir = self.backup_root / safe
            state_dir.mkdir(parents=True, exist_ok=True)
            config_path = repo / ".codira" / "config.toml"
            if config_path.is_file():
                shutil.copy2(config_path, state_dir / "config.toml")
                (state_dir / "state").write_text("present\n", encoding="utf-8")
            else:
                (state_dir / "state").write_text("absent\n", encoding="utf-8")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """
        Restore configured repositories.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type, when the wrapped block raised.
        exc : BaseException | None
            Exception instance, when the wrapped block raised.
        tb : types.TracebackType | None
            Exception traceback, when the wrapped block raised.

        Returns
        -------
        None
            Repository configs are restored in place.
        """

        self.restore()

    def restore(self) -> None:
        """
        Restore backed up repository configs.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Repository configs are restored or removed to match backup state.
        """

        for repo in self.repos:
            safe = safe_slug(str(repo))
            state_dir = self.backup_root / safe
            state_path = state_dir / "state"
            config_path = repo / ".codira" / "config.toml"
            if (
                state_path.is_file()
                and state_path.read_text(encoding="utf-8").strip() == "present"
            ):
                config_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(state_dir / "config.toml", config_path)
            else:
                config_path.unlink(missing_ok=True)
                with suppress(OSError):
                    config_path.parent.rmdir()


def repo_root() -> Path:
    """
    Return the repository root.

    Parameters
    ----------
    None

    Returns
    -------
    pathlib.Path
        Absolute repository root.
    """

    return REPO_ROOT


def resolve_python() -> str:
    """
    Resolve the Python executable used by repository scripts.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Python executable path.

    Raises
    ------
    SystemExit
        If no executable Python can be resolved.
    """

    configured = os.environ.get("PYTHON")
    candidates = [
        configured,
        str(Path(os.environ["VIRTUAL_ENV"]) / "bin" / "python")
        if os.environ.get("VIRTUAL_ENV")
        else None,
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    message = "ERROR: Python executable not found"
    raise SystemExit(message)


def resolve_codira() -> str:
    """
    Resolve the Codira executable used by benchmark scripts.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Codira executable path.

    Raises
    ------
    SystemExit
        If no executable Codira command can be resolved.
    """

    configured = os.environ.get("CODIRA")
    candidates = [
        configured,
        str(Path(os.environ["VIRTUAL_ENV"]) / "bin" / "codira")
        if os.environ.get("VIRTUAL_ENV")
        else None,
        str(REPO_ROOT / ".venv" / "bin" / "codira"),
        str(REPO_ROOT / ".venv" / "Scripts" / "codira.exe"),
        shutil.which("codira"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    message = "ERROR: Codira executable not found"
    raise SystemExit(message)


def run(  # noqa: PLR0913
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = False,
    stdout: int | None = None,
    stderr: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run one subprocess.

    Parameters
    ----------
    args : collections.abc.Sequence[str]
        Command vector.
    cwd : pathlib.Path | None, optional
        Working directory. Defaults to the repository root.
    env : collections.abc.Mapping[str, str] | None, optional
        Process environment. Defaults to the current environment.
    check : bool, optional
        Whether to raise on non-zero exit.
    stdout : int | None, optional
        Standard output routing.
    stderr : int | None, optional
        Standard error routing.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed process metadata.
    """

    return subprocess.run(
        list(args),
        cwd=str(cwd or REPO_ROOT),
        env=dict(env) if env is not None else None,
        check=check,
        text=True,
        stdout=stdout,
        stderr=stderr,
    )


def output(args: Sequence[str], *, cwd: Path | None = None) -> str:
    """
    Return stdout from one subprocess.

    Parameters
    ----------
    args : collections.abc.Sequence[str]
        Command vector.
    cwd : pathlib.Path | None, optional
        Working directory. Defaults to the repository root.

    Returns
    -------
    str
        Captured standard output.
    """

    return subprocess.check_output(list(args), cwd=str(cwd or REPO_ROOT), text=True)


def tee_run(args: Sequence[str], log_path: Path, *, env: Mapping[str, str]) -> int:
    """
    Run a subprocess while teeing combined output to stdout and a log file.

    Parameters
    ----------
    args : collections.abc.Sequence[str]
        Command vector.
    log_path : pathlib.Path
        File receiving combined stdout and stderr.
    env : collections.abc.Mapping[str, str]
        Process environment.

    Returns
    -------
    int
        Child process exit status.
    """

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            list(args),
            cwd=str(REPO_ROOT),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            log_file.write(line)
        return process.wait()


def safe_slug(value: str) -> str:
    """
    Render a filesystem-safe slug.

    Parameters
    ----------
    value : str
        Input value.

    Returns
    -------
    str
        Slug containing only stable path-safe characters.
    """

    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def format_duration(seconds: int) -> str:
    """
    Format an elapsed duration.

    Parameters
    ----------
    seconds : int
        Total seconds.

    Returns
    -------
    str
        Human-readable duration.
    """

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remainder = seconds % 60
    if hours:
        return f"{hours}h {minutes:02d}m {remainder:02d}s"
    if minutes:
        return f"{minutes}m {remainder:02d}s"
    return f"{remainder}s"


def epoch_seconds() -> int:
    """
    Return the current integer epoch timestamp.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Current timestamp.
    """

    return int(time.time())
