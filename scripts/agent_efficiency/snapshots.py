"""Admit public synthetic fixtures by a complete content-addressed inventory.

Parameters
----------
None

Returns
-------
None
    Snapshot transport complements immutable Git archives.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import hashlib
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from scripts.agent_efficiency.contracts import canonical_fingerprint


def snapshot_files(root: Path) -> dict[str, str]:
    """Hash all public fixture files, rejecting links and runtime directories.

    Parameters
    ----------
    root : pathlib.Path
        Checked-in synthetic fixture source.

    Returns
    -------
    dict[str, str]
        Sorted relative file inventory.

    Raises
    ------
    ValueError
        If source includes links or is empty.
    """
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if any(
            part in {".git", ".venv", "node_modules", "__pycache__", ".codira"}
            for part in path.relative_to(root).parts
        ):
            continue
        if path.is_symlink():
            raise ValueError("snapshot fixtures cannot contain symbolic links")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    if not result:
        raise ValueError("snapshot fixture is empty")
    return result


def export_snapshot(source: Path, revision: str, destination: Path) -> None:
    """Export exactly the admitted source inventory into a new workspace.

    Parameters
    ----------
    source : pathlib.Path
        Public synthetic source.
    revision : str
        First forty hexadecimal characters of the complete inventory digest.
    destination : pathlib.Path
        New or empty workspace.

    Returns
    -------
    None
        Only inventoried source files are copied.

    Raises
    ------
    ValueError
        If the source inventory differs from the admitted revision.
    """
    files = snapshot_files(source)
    if canonical_fingerprint(files)[:40] != revision:
        raise ValueError("snapshot source differs from the admitted revision")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
