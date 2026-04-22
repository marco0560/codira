#!/usr/bin/env python3
"""Clean repository artifacts using git-ignored metadata.

Responsibilities
----------------
- Enumerate git-ignored paths while respecting protected directories.
- Remove ignored files or report planned actions when dry-run mode is enabled.
- Keep protected paths intact and fail fast when Git status cannot be read.

Design principles
-----------------
Cleaning relies on Git as the single source of truth and avoids heuristic deletions by only touching ignored files.

Architectural role
------------------
This module belongs to the **cleanup tooling layer** that keeps working trees tidy without risking tracked files.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Paths that should never be removed, even if ignored by git
PROTECTED_PATHS = {
    Path(".codex"),
    Path(".venv"),
    Path(".vscode"),
    Path("node_modules"),
    Path("src/codira/_version.py"),
    Path(".codira"),
    Path(".artifacts"),
}
GIT_EXE = shutil.which("git") or "git"


def git_ignored_paths() -> Iterable[Path]:
    """
    Yield Git-ignored paths reported by ``git status``.

    Parameters
    ----------
    None

    Yields
    ------
    pathlib.Path
        Ignored repository-relative paths.

    Raises
    ------
    subprocess.CalledProcessError
        If ``git status --ignored --porcelain`` fails.
    """
    result = subprocess.run(
        [GIT_EXE, "status", "--ignored", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )

    for line in result.stdout.splitlines():
        if line.startswith("!! "):
            yield Path(line[3:])


def remove_path(path: Path, dry_run: bool) -> None:
    """
    Remove a filesystem path or report the action in dry-run mode.

    Parameters
    ----------
    path : pathlib.Path
        File or directory path to remove.
    dry_run : bool
        Whether to print the planned action without mutating the filesystem.

    Returns
    -------
    None
        The path is removed in place or only reported when ``dry_run`` is
        enabled.
    """
    if dry_run:
        print(f"[DRY-RUN] Would remove: {path}")
        return

    if path.is_dir():
        shutil.rmtree(path)
        print(f"Removed directory: {path}")
    elif path.exists():
        path.unlink()
        print(f"Removed file: {path}")


def main() -> None:
    """
    Remove ignored repository artifacts while preserving protected paths.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The script removes ignored paths in place or reports the planned
        actions in dry-run mode.

    Notes
    -----
    Protected paths are filtered before deletion, even when Git reports them
    as ignored.
    """
    parser = argparse.ArgumentParser(
        description="Clean repository by removing ignored artifacts"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything",
    )
    args = parser.parse_args()

    repo_root = Path.cwd()

    ignored = []

    for path in git_ignored_paths():
        if any(
            path == protected or protected in path.parents
            for protected in PROTECTED_PATHS
        ):
            continue
        ignored.append(path)

    if not ignored:
        print("Nothing to clean.")
        return

    for path in ignored:
        remove_path(repo_root / path, dry_run=args.dry_run)

    if args.dry_run:
        print("\nDry-run completed.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
