#!/usr/bin/env python3
"""Check local release tooling wiring."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import output, run


def main() -> int:
    """
    Run release tooling self-checks.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status.
    """

    print("== Release system self-check ==")
    failed = False

    print("[1] Checking hooks path...")
    hooks = output(["git", "config", "core.hooksPath"]).strip()
    if hooks != ".githooks":
        print("FAIL: hooksPath not .githooks")
        failed = True

    print("[2] Checking required scripts...")
    for path in (
        Path("scripts/release_audit.py"),
        Path("scripts/tag_guard.py"),
        Path("scripts/changelog_guard.py"),
        Path("scripts/release_rel.py"),
    ):
        if not path.is_file():
            print(f"FAIL: missing {path}")
            failed = True

    print("[3] Checking pre-push hook exists...")
    if not Path(".githooks/pre-push").is_file():
        print("FAIL: missing pre-push")
        failed = True

    print("[4] Checking release alias...")
    if run(["git", "config", "alias.rel"]).returncode:
        print("FAIL: alias.rel missing")
        failed = True

    print("[5] Checking history not rewritten...")
    first_tags = output(["git", "tag", "--sort=v:refname"]).splitlines()
    if (
        first_tags
        and run(
            ["git", "merge-base", "--is-ancestor", first_tags[0], "HEAD"]
        ).returncode
    ):
        print("FAIL: history rewritten after first release")
        failed = True

    print("[6] Checking latest tag reachable...")
    latest_tags = output(
        ["git", "tag", "--merged", "HEAD", "--sort=-v:refname"]
    ).splitlines()
    if (
        latest_tags
        and run(
            ["git", "merge-base", "--is-ancestor", latest_tags[0], "HEAD"]
        ).returncode
    ):
        print("FAIL: latest tag not ancestor of HEAD")
        failed = True

    print("[7] Checking semantic-release baseline...")
    if run(["npx", "semantic-release", "--dry-run"], stdout=-3, stderr=-3).returncode:
        print("WARN: semantic-release dry-run failed")

    if failed:
        print("FAIL: release system inconsistent")
        return 1
    print("OK: release system consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
