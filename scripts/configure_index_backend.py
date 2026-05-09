#!/usr/bin/env python3
"""Configure the active codira index backend for the current shell.

Responsibilities
----------------
- Report the currently configured backend for the current process.
- Emit shell code that activates the requested backend in an env-only workflow.
- Refresh the target backend index when switching between backend names.

Design principles
-----------------
The script keeps backend selection env-based, prints only shell code to
standard output, and delegates rebuild decisions to ``codira index``.

Architectural role
------------------
This module belongs to the **developer tooling layer** and provides a portable
backend-switch entrypoint for repository-local shells.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from codira.registry import (
    DEFAULT_INDEX_BACKEND,
    INDEX_BACKEND_ENV_VAR,
    configured_index_backend_name,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def uv_executable() -> str:
    """
    Return the preferred ``uv`` executable for repository-local commands.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Resolved ``uv`` executable path, or ``"uv"`` when it is already on
        ``PATH``.
    """

    return shutil.which("uv") or "uv"


def shell_activate_command(backend_name: str) -> str:
    """
    Render shell code that activates one backend in the current shell.

    Parameters
    ----------
    backend_name : str
        Backend name to activate.

    Returns
    -------
    str
        Shell code that configures ``CODIRA_INDEX_BACKEND`` for bash-like
        shells. The default SQLite backend is represented by unsetting the
        variable.
    """

    if backend_name == DEFAULT_INDEX_BACKEND:
        return f"unset {INDEX_BACKEND_ENV_VAR}"
    return f"export {INDEX_BACKEND_ENV_VAR}={backend_name}"


def run_backend_reindex(repo_root: Path, backend_name: str) -> None:
    """
    Refresh the local index under one selected backend environment.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root whose index should be refreshed.
    backend_name : str
        Backend name to activate during the refresh.

    Returns
    -------
    None
        The repository index is refreshed in place when the backend switch is
        requested.

    Raises
    ------
    subprocess.CalledProcessError
        Raised when ``codira index`` fails for the requested backend.
    """

    env = os.environ.copy()
    if backend_name == DEFAULT_INDEX_BACKEND:
        env.pop(INDEX_BACKEND_ENV_VAR, None)
    else:
        env[INDEX_BACKEND_ENV_VAR] = backend_name

    print(
        f"[codira] Switching backend to {backend_name} and refreshing the index...",
        file=sys.stderr,
    )
    subprocess.run(
        [uv_executable(), "run", "codira", "index"],
        check=True,
        cwd=repo_root,
        env=env,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser for backend selection.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser for the backend-switch helper.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Print shell code that activates one codira backend for the current "
            "shell. Use eval or source so the exported environment variable "
            "survives after the script exits."
        ),
        epilog=(
            "Examples:\n"
            '  eval "$(uv run python scripts/configure_index_backend.py duckdb)"\n'
            '  eval "$(uv run python scripts/configure_index_backend.py sqlite)"\n'
            "  uv run python scripts/configure_index_backend.py help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "backend",
        nargs="?",
        default="help",
        choices=("help", "sqlite", "duckdb"),
        help="Target backend name, or `help` to print this message.",
    )
    return parser


def print_help_with_current_backend(parser: argparse.ArgumentParser) -> None:
    """
    Print usage text plus the currently configured backend name.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Parser whose help message should be rendered.

    Returns
    -------
    None
        Help text is printed to standard output.
    """

    parser.print_help()
    print()
    print(f"Current backend: {configured_index_backend_name()}")


def main(argv: list[str] | None = None) -> int:
    """
    Configure one backend or print the current backend selection help text.

    Parameters
    ----------
    argv : list[str] | None, optional
        Explicit command arguments. ``None`` uses ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit status for the backend-switch helper.
    """

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.backend == "help":
        print_help_with_current_backend(parser)
        return 0

    current_backend = configured_index_backend_name()
    target_backend = args.backend
    if current_backend != target_backend:
        run_backend_reindex(REPO_ROOT, target_backend)

    print(shell_activate_command(target_backend))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
