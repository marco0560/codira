"""Regression tests for maintained lint-suppression policy."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "process" / "lint-and-semgrep-hygiene.md"
NOQA_PATTERN = re.compile(r"#\s*noqa(?:\b|:)")
NOSEMGREP_PATTERN = re.compile(r"#\s*nosemgrep:")


def test_every_noqa_location_is_documented_in_quality_policy() -> None:
    """Require a maintained reason for every current Ruff suppression.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts every source location containing a Ruff suppression
        marker has an exact entry in the maintained hygiene-policy inventory.
    """
    policy = POLICY_PATH.read_text(encoding="utf-8")
    locations: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in {".git", ".venv", "build"} for part in path.parts):
            continue
        relative = path.relative_to(REPO_ROOT)
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if NOQA_PATTERN.search(line):
                locations.append(f"{relative}:{line_number}")

    undocumented = [location for location in locations if location not in policy]
    assert undocumented == []


def test_every_nosemgrep_source_is_documented_in_quality_policy() -> None:
    """Require an explicit source owner for each external-rule exception.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts every Python source containing a ``nosemgrep`` marker
        is named in the maintained hygiene-policy exception record.
    """
    policy = POLICY_PATH.read_text(encoding="utf-8")
    sources: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in {".git", ".venv", "build"} for part in path.parts):
            continue
        if NOSEMGREP_PATTERN.search(path.read_text(encoding="utf-8")):
            sources.append(path.relative_to(REPO_ROOT).as_posix())

    undocumented = [source for source in sources if source not in policy]
    assert undocumented == []
