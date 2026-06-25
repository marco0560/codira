#!/usr/bin/env python3
"""Run conservative release-readiness checks."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
    print(
        "Usage: python scripts/release_audit.py [-h|--help]\n\n"
        "Run conservative release-readiness checks."
    )
    raise SystemExit(0)

from scripts.scriptlib import output, run


def latest_reachable_tag() -> str:
    """
    Return the latest reachable semantic version tag.

    Parameters
    ----------
    None

    Returns
    -------
    str
        Latest reachable semantic version tag, or an empty string.
    """

    tags = [
        line.strip()
        for line in output(
            ["git", "tag", "--merged", "HEAD", "--sort=v:refname"]
        ).splitlines()
        if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", line.strip())
    ]
    return tags[-1] if tags else ""


def main() -> int:
    """
    Run release-readiness checks.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    if os.environ.get("SKIP_RELEASE_AUDIT") == "1":
        return 0

    print("== Release Audit ==")
    print("[1] Checking working tree clean...")
    if (
        run(["git", "diff", "--quiet"]).returncode
        or run(["git", "diff", "--cached", "--quiet"]).returncode
    ):
        print("ERROR: dirty working tree")
        return 1

    print("[2] Checking branch alignment...")
    local = output(["git", "rev-parse", "@"]).strip()
    try:
        remote = output(["git", "rev-parse", "@{u}"]).strip()
    except subprocess.CalledProcessError:
        remote = ""
    if not remote:
        print("OK: no upstream configured")
    else:
        base = output(["git", "merge-base", "@", "@{u}"]).strip()
        if local == remote:
            print("OK: branch aligned")
        elif local == base:
            print("ERROR: branch behind remote")
            return 1
        elif remote == base:
            print("OK: branch ahead")
        else:
            print("ERROR: branch diverged")
            return 1

    branch = output(["git", "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch != "main":
        print(f"Release audit skipped on branch {branch}")
        return 0

    print("[3] Checking latest tag ancestry...")
    latest_tag = latest_reachable_tag()
    if not latest_tag:
        print("WARN: no semantic version tag reachable from HEAD")
    else:
        tag_status = run(
            [os.environ.get("PYTHON", "python"), "-m", "scripts.tag_guard", latest_tag]
        ).returncode
        if tag_status:
            return tag_status
        if (
            run(["git", "merge-base", "--is-ancestor", latest_tag, "HEAD"]).returncode
            == 0
        ):
            print(f"OK: latest tag consistent ({latest_tag})")
        else:
            print("ERROR: latest tag is not an ancestor of HEAD")
            return 1

    print("[4] Checking changelog consistency...")
    changelog_status = run(
        [os.environ.get("PYTHON", "python"), "-m", "scripts.changelog_guard"]
    ).returncode
    if changelog_status:
        return changelog_status

    print("[5] Checking semantic-release baseline...")
    if latest_tag:
        commits = output(["git", "rev-list", f"{latest_tag}..HEAD", "--count"]).strip()
    else:
        commits = output(["git", "rev-list", "HEAD", "--count"]).strip()
    print(f"Commits since last reachable release: {commits}")

    print("[6] Checking release commit count...")
    release_commits = output(
        ["git", "log", "--oneline", "--grep", "^chore(release):"]
    ).splitlines()
    print(f"Release commits in history: {len(release_commits)}")
    print("OK: release baseline valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
