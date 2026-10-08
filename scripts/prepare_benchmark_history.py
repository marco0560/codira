#!/usr/bin/env python3
"""Verify or fetch the frozen Codira revisions needed by benchmark tests.

Parameters
----------
None

Returns
-------
None
    Git history preparation does not change manifests or run model calls.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "git"


def required_revisions(root: Path) -> tuple[str, ...]:
    """Read exact immutable revisions from the existing benchmark manifests.

    Parameters
    ----------
    root : pathlib.Path
        Checkout containing the public fixture and reviewer manifests.

    Returns
    -------
    tuple[str, ...]
        Sorted unique full commit IDs, never mutable branch names or Git flags.

    Raises
    ------
    ValueError
        If a revision is not a full lowercase SHA-1 commit ID.
    OSError
        If a manifest cannot be read.
    KeyError
        If a required manifest field is absent.
    """
    corpus = root / "benchmarks/agent-efficiency"
    fixture = json.loads((corpus / "fixtures/codira-public.json").read_text())
    reviewer = json.loads(
        (corpus / "reviewer-evaluation/phase6-deepseek-v4-1-flash.json").read_text()
    )
    revisions = [fixture["revision"]]
    revisions.extend(
        case[key] for case in reviewer["cases"] for key in ("base", "head")
    )
    if not revisions or any(
        not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        for revision in revisions
    ):
        message = "benchmark revisions must be full lowercase commit IDs"
        raise ValueError(message)
    return tuple(sorted(set(revisions)))


def prepare_history(root: Path, *, fetch: bool = False) -> tuple[str, ...]:
    """Verify commit objects, optionally retrieving the frozen IDs from origin.

    Parameters
    ----------
    root : pathlib.Path
        Repository whose object database is verified.
    fetch : bool, optional
        Fetch all pinned revisions before verification. This mode needs network
        access and modifies only Git objects and FETCH_HEAD.

    Returns
    -------
    tuple[str, ...]
        Missing commit IDs after the optional fetch; empty means ready.

    Raises
    ------
    subprocess.CalledProcessError
        If the exact origin fetch fails.
    OSError
        If Git or a manifest is unavailable.
    ValueError
        If a manifest revision is invalid.
    KeyError
        If a manifest is incomplete.
    """
    revisions = required_revisions(root)
    if fetch:
        subprocess.run(
            (GIT, "-C", str(root), "fetch", "--no-tags", "origin", *revisions),
            check=True,
        )
    return tuple(
        revision
        for revision in revisions
        if subprocess.run(
            (GIT, "-C", str(root), "cat-file", "-e", f"{revision}^{{commit}}"),
            check=False,
            capture_output=True,
        ).returncode
        != 0
    )


def main(arguments: list[str] | None = None) -> int:
    """Print missing frozen history and exit nonzero until it is available.

    Parameters
    ----------
    arguments : list[str] or None, optional
        ``--fetch`` opts into origin access; the default is an offline check.

    Returns
    -------
    int
        Zero for complete history, one for missing commits, two for invalid
        manifests or an unsuccessful fetch.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true")
    options = parser.parse_args(arguments)
    try:
        missing = prepare_history(REPO_ROOT, fetch=options.fetch)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        print(
            "Frozen benchmark history preparation failed; inspect manifests and Git access."
        )
        return 2
    print(json.dumps({"missing_revisions": missing, "fetched": options.fetch}))
    return int(bool(missing))


if __name__ == "__main__":
    raise SystemExit(main())
