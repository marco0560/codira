"""Read minimal Git repository state for Codira runtime coordination.

Responsibilities
----------------
- Resolve the commit currently checked out by a repository working tree.
- Keep Git subprocess behavior independent from CLI presentation concerns.

Design principles
-----------------
Git state is advisory runtime information: unavailable or non-Git roots
produce ``None`` instead of preventing explicit indexing.

Architectural role
------------------
This module belongs to the repository-state infrastructure layer shared by
the CLI freshness checks and the optional daemon scheduler.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

GIT_EXE = shutil.which("git") or "git"


def read_head_commit(root: Path) -> str | None:
    """Read the current Git commit hash for one repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the Git subprocess working directory.

    Returns
    -------
    str | None
        Current ``HEAD`` commit hash, or ``None`` if it cannot be read.
    """
    try:
        result = subprocess.run(
            [GIT_EXE, "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def is_git_ignored(root: Path, path: Path) -> bool:
    """Return whether one repository path matches active Git ignore rules.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used as the Git subprocess working directory.
    path : pathlib.Path
        Candidate path to evaluate against ``.gitignore`` and related Git
        ignore sources.

    Returns
    -------
    bool
        ``True`` when Git identifies the path as ignored. A missing Git binary,
        non-Git root, or Git diagnostic returns ``False`` so the daemon does
        not silently miss source changes.
    """
    resolved_root = root.resolve()
    try:
        relative_path = path.resolve().relative_to(resolved_root)
    except ValueError:
        return False
    try:
        result = subprocess.run(
            [
                GIT_EXE,
                "check-ignore",
                "--quiet",
                "--no-index",
                "--",
                relative_path.as_posix(),
            ],
            cwd=resolved_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0
