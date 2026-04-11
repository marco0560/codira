#!/usr/bin/env python3
"""Validate commit message headers used in this repository.

Responsibilities
----------------
- Parse commit headers over a revision range and enforce conventional commit syntax.
- Reject unsafe scope characters while accepting lowercase release-safe values.
- Provide a CLI entry point so automation or hooks can gate unsafe headers.

Design principles
-----------------
Validator keeps scope rules explicit, deterministic, and fails fast before commits reach protected branches.

Architectural role
------------------
This script belongs to the **tooling layer** guarding repository release hygiene.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

HEADER_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?: (?P<subject>.+)$"
)
SAFE_SCOPE_RE = re.compile(r"^[a-z0-9/_-]+$")
ZERO_SHA = "0" * 40
GIT_EXE = shutil.which("git") or "git"


@dataclass(frozen=True)
class CommitHeader:
    """
    Parsed commit header.

    Parameters
    ----------
    sha : str
        Commit SHA.
    header : str
        First line of the commit message.
    scope : str | None
        Parsed scope value when present.
    """

    sha: str
    header: str
    scope: str | None


def git_stdout(*args: str) -> str:
    """
    Run a git command and return stdout.

    Parameters
    ----------
    *args : str
        Arguments passed to `git`.

    Returns
    -------
    str
        Command stdout.
    """

    result = subprocess.run(
        [GIT_EXE, *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def iter_commit_headers(revision_range: str) -> list[CommitHeader]:
    """
    Collect commit headers from a revision range.

    Parameters
    ----------
    revision_range : str
        Git revision range or single revision.

    Returns
    -------
    list[CommitHeader]
        Commit SHAs and their first-line headers.
    """

    raw = git_stdout("log", "--format=%H%x00%s", revision_range)
    headers: list[CommitHeader] = []

    for line in raw.splitlines():
        sha, header = line.split("\x00", maxsplit=1)
        match = HEADER_RE.match(header)
        scope = match.group("scope") if match else None
        headers.append(CommitHeader(sha=sha, header=header, scope=scope))

    return headers


def validate_header(commit: CommitHeader) -> str | None:
    """
    Validate a single commit header.

    Parameters
    ----------
    commit : CommitHeader
        Commit header to validate.

    Returns
    -------
    str | None
        Validation error, or ``None`` when the header is accepted.
    """

    if commit.scope is None:
        return None

    if SAFE_SCOPE_RE.fullmatch(commit.scope):
        return None

    return (
        f"{commit.sha[:7]}: invalid scope {commit.scope!r} in {commit.header!r}. "
        "Use only lowercase letters, digits, '/', '_' or '-'."
    )


def resolve_revision_range(base: str | None, head: str | None) -> str:
    """
    Resolve the git revision range to inspect.

    Parameters
    ----------
    base : str | None
        Base commit SHA.
    head : str | None
        Head commit SHA.

    Returns
    -------
    str
        Revision range or single revision string.

    Raises
    ------
    ValueError
        If no revision target is provided.
    """

    if head and base and base != ZERO_SHA:
        return f"{base}..{head}"
    if head:
        return head
    msg = "A head revision is required."
    raise ValueError(msg)


def main() -> int:
    """
    Run commit header validation.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """

    parser = argparse.ArgumentParser(
        description="Validate commit headers for semantic-release compatibility."
    )
    parser.add_argument("--base", help="Base commit SHA for the revision range.")
    parser.add_argument("--head", help="Head commit SHA for the revision range.")
    args = parser.parse_args()

    try:
        revision_range = resolve_revision_range(args.base, args.head)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    errors = [
        error
        for commit in iter_commit_headers(revision_range)
        if (error := validate_header(commit)) is not None
    ]

    if errors:
        print("Commit message validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Commit message validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
