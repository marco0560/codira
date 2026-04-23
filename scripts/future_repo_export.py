#!/usr/bin/env python3
"""Materialize future split repositories from the accepted path manifest.

Responsibilities
----------------
- Turn the reviewed multirepo split manifest into a deterministic copy plan.
- Materialize one future repository into an empty destination directory.
- Keep split rehearsal grounded in explicit owned paths rather than ad hoc file
  selection.

Design principles
-----------------
The helper is path-based, conservative, and non-destructive. It refuses to
write into a non-empty destination and never invents ownership outside the
accepted manifest.

Architectural role
------------------
This script belongs to the **developer tooling layer** and provides the
mechanical extraction step needed to rehearse Phase 3 of the packaging
migration.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.future_repo_split_manifest import FutureRepoSplitManifest
    from scripts.future_repo_split_manifest import (
        future_repo_split_manifests as _future_repo_split_manifests,
    )
else:
    from future_repo_split_manifest import FutureRepoSplitManifest
    from future_repo_split_manifest import (
        future_repo_split_manifests as _future_repo_split_manifests,
    )

future_repo_split_manifests = _future_repo_split_manifests


@dataclass(frozen=True)
class FutureRepoExportEntry:
    """
    Declarative copy step for one path in a future repository export plan.

    Parameters
    ----------
    source : pathlib.Path
        Repository-local source path to copy from the monorepo checkout.
    target_relative : pathlib.PurePosixPath
        Relative path that the exported repository should contain.
    """

    source: Path
    target_relative: PurePosixPath


def export_manifest_for(repository: str) -> FutureRepoSplitManifest:
    """
    Return the accepted split manifest for one future repository.

    Parameters
    ----------
    repository : str
        Future repository name.

    Returns
    -------
    FutureRepoSplitManifest
        Accepted split manifest for ``repository``.

    Raises
    ------
    ValueError
        If ``repository`` is not part of the accepted multirepo topology.
    """
    for manifest in future_repo_split_manifests():
        if manifest.repository == repository:
            return manifest
    message = f"Unknown future repository: {repository}"
    raise ValueError(message)


def build_future_repo_export_plan(
    repo_root: Path,
    repository: str,
) -> tuple[FutureRepoExportEntry, ...]:
    """
    Build the deterministic export plan for one future repository.

    Parameters
    ----------
    repo_root : pathlib.Path
        Monorepo root to export from.
    repository : str
        Future repository name.

    Returns
    -------
    tuple[FutureRepoExportEntry, ...]
        Copy steps in manifest order.

    Raises
    ------
    ValueError
        If the repository is unknown or its owned paths cannot be mapped to the
        exported repository root.
    """
    manifest = export_manifest_for(repository)
    return tuple(
        FutureRepoExportEntry(
            source=repo_root / source_relative,
            target_relative=_target_relative_path(
                repository=repository,
                source_relative=source_relative,
            ),
        )
        for source_relative in manifest.owned_paths
    )


def materialize_future_repo(
    repo_root: Path,
    repository: str,
    destination_root: Path,
) -> Path:
    """
    Materialize one future repository into an empty destination directory.

    Parameters
    ----------
    repo_root : pathlib.Path
        Monorepo root to export from.
    repository : str
        Future repository name.
    destination_root : pathlib.Path
        Directory under which the exported repository directory will be created.

    Returns
    -------
    pathlib.Path
        Path to the created repository directory.

    Raises
    ------
    FileNotFoundError
        If a declared owned path does not exist in the monorepo checkout.
    ValueError
        If the destination repository directory already exists and is not empty.
    """
    export_dir = destination_root / repository
    if export_dir.exists() and any(export_dir.iterdir()):
        message = f"Destination repository directory is not empty: {export_dir}"
        raise ValueError(message)
    export_dir.mkdir(parents=True, exist_ok=True)
    for entry in build_future_repo_export_plan(repo_root, repository):
        _copy_export_entry(entry=entry, export_dir=export_dir)
    return export_dir


def _target_relative_path(repository: str, source_relative: str) -> PurePosixPath:
    """
    Map one manifest path from the monorepo to the exported repository root.

    Parameters
    ----------
    repository : str
        Future repository name.
    source_relative : str
        Repository-relative source path from the monorepo.

    Returns
    -------
    pathlib.PurePosixPath
        Relative path inside the exported repository.

    Raises
    ------
    ValueError
        If the manifest path is incompatible with the repository export rules.
    """
    if repository == "codira":
        return PurePosixPath(source_relative.rstrip("/"))
    package_prefix = f"packages/{repository}/"
    if not source_relative.startswith(package_prefix):
        message = (
            f"Owned path {source_relative!r} does not live under " f"{package_prefix!r}"
        )
        raise ValueError(message)
    suffix = source_relative.removeprefix(package_prefix).rstrip("/")
    return PurePosixPath(suffix)


def _copy_export_entry(entry: FutureRepoExportEntry, export_dir: Path) -> None:
    """
    Copy one export entry into the destination repository directory.

    Parameters
    ----------
    entry : FutureRepoExportEntry
        Planned source and target-relative paths for the export step.
    export_dir : pathlib.Path
        Destination repository directory.

    Returns
    -------
    None

    Raises
    ------
    FileNotFoundError
        If the declared source path does not exist.
    """
    if not entry.source.exists():
        message = f"Missing owned path declared in split manifest: {entry.source}"
        raise FileNotFoundError(message)
    target = export_dir.joinpath(*entry.target_relative.parts)
    if entry.source.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(entry.source, target, dirs_exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(entry.source, target)


def _build_parser() -> argparse.ArgumentParser:
    """
    Build the command-line parser for future repository exports.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Plan or materialize one future repository from the accepted "
            "multirepo split manifest."
        )
    )
    parser.add_argument("repository", help="Future repository name to export")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Monorepo root to export from",
    )
    parser.add_argument(
        "--destination-root",
        type=Path,
        help="Destination directory under which the exported repository will be created",
    )
    return parser


def main() -> int:
    """
    Run the future repository export helper.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status code.
    """
    args = _build_parser().parse_args()
    plan = build_future_repo_export_plan(
        repo_root=args.repo_root,
        repository=args.repository,
    )
    for entry in plan:
        print(f"{entry.source.relative_to(args.repo_root)} -> {entry.target_relative}")
    if args.destination_root is None:
        return 0
    materialize_future_repo(
        repo_root=args.repo_root,
        repository=args.repository,
        destination_root=args.destination_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
