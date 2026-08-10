#!/usr/bin/env python3
"""Shared first-party package inventory for repository-local tooling.

Responsibilities
----------------
- Define the authoritative repository-local first-party package list.
- Resolve first-party package directories from a repository root.
- Keep install, build-rehearsal, and bootstrap helpers aligned to one source of truth.

Design principles
-----------------
The helper stays small and deterministic so packaging workflows can share one
package inventory without duplicating ordering decisions.

Architectural role
------------------
This script belongs to the **developer tooling layer** and centralizes the
accepted first-party package boundary used across migration tooling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "packages" / "first_party_packages.json"


def load_first_party_manifest() -> dict[str, object]:
    """Load the canonical first-party package manifest.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Parsed manifest data.
    """
    return cast(
        "dict[str, object]", json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    )


FIRST_PARTY_PACKAGE_DIRS: tuple[str, ...] = tuple(
    cast("str", package["path"])
    for package in cast(
        "list[dict[str, object]]", load_first_party_manifest()["packages"]
    )
)


def package_paths(repo_root: Path) -> tuple[Path, ...]:
    """
    Return first-party package directories in deterministic order.

    Parameters
    ----------
    repo_root : pathlib.Path
        Repository root containing the first-party packages.

    Returns
    -------
    tuple[pathlib.Path, ...]
        First-party package directories resolved from ``repo_root``.
    """
    return tuple(repo_root / relative for relative in FIRST_PARTY_PACKAGE_DIRS)
