"""Resolve CLI target and output directories deterministically.

Responsibilities
----------------
- Centralize repository target and index output path resolution for CLI commands.
- Apply stable precedence across CLI flags, environment variables, and defaults.
- Validate absolute target/output paths before command dispatch.

Design principles
-----------------
Path resolution is explicit, deterministic, and rejects ambiguous or invalid
configurations early.

Architectural role
------------------
This module belongs to the **CLI support layer** and keeps path-selection
policy out of individual command handlers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

CODIRA_TARGET_DIR_ENV = "CODIRA_TARGET_DIR"
CODIRA_OUTPUT_DIR_ENV = "CODIRA_OUTPUT_DIR"


@dataclass(frozen=True)
class ResolvedRuntimePaths:
    """
    Resolved read and write roots for one CLI command.

    Parameters
    ----------
    target_root : pathlib.Path
        Absolute repository root used for all reads and analyzer scans.
    output_root : pathlib.Path
        Absolute directory under which ``.codira`` state is stored.
    """

    target_root: Path
    output_root: Path


def _resolve_candidate_directory(raw_path: str, *, must_exist: bool) -> Path:
    """
    Resolve one user-supplied directory path to an absolute path.

    Parameters
    ----------
    raw_path : str
        User-supplied filesystem path.
    must_exist : bool
        Whether the directory must already exist.

    Returns
    -------
    pathlib.Path
        Absolute normalized path.
    """

    return Path(raw_path).expanduser().resolve(strict=must_exist)


def _nearest_existing_parent(path: Path) -> Path:
    """
    Return the nearest existing parent for one candidate path.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path that may not exist yet.

    Returns
    -------
    pathlib.Path
        Existing directory used for writability checks.
    """

    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return candidate
        candidate = parent
    return candidate


def _validate_target_root(parser: argparse.ArgumentParser, target_root: Path) -> None:
    """
    Fail fast when the target root is missing or not a directory.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active parser used for deterministic error reporting.
    target_root : pathlib.Path
        Absolute target directory to validate.

    Returns
    -------
    None
        The function returns only for a valid target directory.
    """

    if not target_root.exists():
        parser.error(f"Target directory does not exist: {target_root}")
    if not target_root.is_dir():
        parser.error(f"Target path is not a directory: {target_root}")


def _validate_output_root(parser: argparse.ArgumentParser, output_root: Path) -> None:
    """
    Fail fast when the output root cannot host ``.codira`` state.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active parser used for deterministic error reporting.
    output_root : pathlib.Path
        Absolute output directory to validate.

    Returns
    -------
    None
        The function returns only for a writable output directory.
    """

    if output_root.exists() and not output_root.is_dir():
        parser.error(f"Output directory is not a directory: {output_root}")

    writable_base = (
        output_root if output_root.exists() else _nearest_existing_parent(output_root)
    )
    if not writable_base.is_dir():
        parser.error(
            f"Output directory is not under a writable directory: {output_root}"
        )
    if not os.access(writable_base, os.W_OK | os.X_OK):
        parser.error(f"Output directory is not writable: {output_root}")


def resolve_runtime_paths(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> ResolvedRuntimePaths:
    """
    Resolve the CLI target and output directories with fixed precedence.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        Active parser used for deterministic error reporting.
    args : argparse.Namespace
        Parsed command-line arguments.

    Returns
    -------
    ResolvedRuntimePaths
        Absolute validated target and output roots.
    """

    raw_target = getattr(args, "path", None) or os.environ.get(CODIRA_TARGET_DIR_ENV)
    raw_output = getattr(args, "output_dir", None) or os.environ.get(
        CODIRA_OUTPUT_DIR_ENV
    )

    target_root = (
        _resolve_candidate_directory(raw_target, must_exist=True)
        if raw_target is not None
        else Path.cwd().resolve()
    )
    _validate_target_root(parser, target_root)

    output_root = (
        _resolve_candidate_directory(raw_output, must_exist=False)
        if raw_output is not None
        else target_root
    )
    _validate_output_root(parser, output_root)

    return ResolvedRuntimePaths(
        target_root=target_root,
        output_root=output_root,
    )
