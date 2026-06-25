#!/usr/bin/env python3
"""Validate changelog release heading consistency."""

from __future__ import annotations

import re
from pathlib import Path

from scripts.scriptlib import output

VERSION_RE = re.compile(r"^#{1,2} \[([0-9][0-9.]*)\].*")


def changelog_versions(path: Path) -> list[str]:
    """
    Extract release versions from a changelog.

    Parameters
    ----------
    path : pathlib.Path
        Changelog path.

    Returns
    -------
    list[str]
        Versions in file order.
    """

    versions: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = VERSION_RE.match(line)
        if match:
            versions.append(match.group(1))
    return versions


def latest_reachable_tag() -> str:
    """
    Return the latest reachable semantic version tag.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Latest reachable tag, or an empty string when none exists.
    """

    tags = [
        line.strip()
        for line in output(
            ["git", "tag", "--merged", "HEAD", "--sort=v:refname"]
        ).splitlines()
        if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", line.strip())
    ]
    if not tags:
        return ""
    return tags[-1]


def main() -> int:
    """
    Run the changelog guard.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    path = Path("CHANGELOG.md")
    if not path.is_file():
        print("ERROR: CHANGELOG.md not found")
        return 1
    versions = changelog_versions(path)
    if not versions:
        print("ERROR: CHANGELOG.md does not start with a released version heading")
        return 1
    duplicates = sorted(
        {version for version in versions if versions.count(version) > 1}
    )
    if duplicates:
        print("ERROR: duplicate release entries found in CHANGELOG.md")
        print("\n".join(duplicates))
        return 1
    latest_tag = latest_reachable_tag()
    if latest_tag and versions[0] != latest_tag.removeprefix("v"):
        print(
            f"ERROR: top CHANGELOG version ({versions[0]}) does not match "
            f"latest tag ({latest_tag})"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
