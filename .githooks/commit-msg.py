#!python
"""Validate codira commit messages for the local ``commit-msg`` hook.

Responsibilities
----------------
- Enforce the repository's Conventional Commit header format.
- Restrict optional scopes to the codira subsystem list documented in
  ``.gitmessage``.
- Print deterministic diagnostics that help contributors repair invalid
  commit messages before they leave the local repository.

Design principles
-----------------
The hook is intentionally small and dependency-free so it can run during Git's
``commit-msg`` phase in a freshly bootstrapped checkout.

Architectural role
------------------
This script belongs to the **developer tooling layer** guarding local commit
metadata before CI repeats commit-message validation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED_TYPES = frozenset(
    {
        "feat",
        "fix",
        "docs",
        "perf",
        "refactor",
        "test",
        "chore",
        "style",
    }
)
ALLOWED_SCOPES = frozenset(
    {
        "analyzer",
        "backend",
        "bootstrap",
        "bundle",
        "ci",
        "cli",
        "config",
        "context",
        "contracts",
        "coverage",
        "dev",
        "docs",
        "embeddings",
        "git",
        "hooks",
        "indexer",
        "package",
        "plugins",
        "process",
        "query",
        "registry",
        "release",
        "scanner",
        "schema",
        "semantic",
        "storage",
        "tests",
        "version",
    }
)
HEADER_RE = re.compile(
    r"^(?P<type>feat|fix|docs|perf|refactor|test|chore|style)"
    r"(\((?P<scope>[a-z0-9/_-]+)\))?"
    r"(?P<breaking>!)?: "
    r"(?P<summary>.{1,72})$"
)


def first_message_line(message_path: Path) -> str:
    """
    Return the first commit-message line to validate.

    Parameters
    ----------
    message_path : pathlib.Path
        Path to the temporary commit message file supplied by Git.

    Returns
    -------
    str
        First line of the commit message with surrounding whitespace removed.
    """
    with message_path.open(encoding="utf-8") as handle:
        return handle.readline().strip()


def print_allowed_values() -> None:
    """
    Print accepted commit types and scopes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The accepted values are written to standard output.
    """
    print("Types admitted:")
    for commit_type in sorted(ALLOWED_TYPES):
        print(f"  - {commit_type}")
    print("Scopes admitted:")
    for scope in sorted(ALLOWED_SCOPES):
        print(f"  - {scope}")


def validate_header(header: str) -> str | None:
    """
    Validate one commit-message header.

    Parameters
    ----------
    header : str
        First line of the commit message.

    Returns
    -------
    str | None
        Validation error message, or ``None`` when the header is valid.
    """
    match = HEADER_RE.match(header)
    if not match:
        return "commit message non compliant"

    scope = match.group("scope")
    if scope and scope not in ALLOWED_SCOPES:
        return f"scope '{scope}' not admitted"

    return None


def main(argv: list[str] | None = None) -> int:
    """
    Run commit-message validation.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments. When omitted, ``sys.argv[1:]`` is used.

    Returns
    -------
    int
        Process exit code where ``0`` means the message is accepted.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("ERROR: commit message path missing.")
        return 2

    message_path = Path(args[0])
    header = first_message_line(message_path)
    error = validate_header(header)
    if error is None:
        return 0

    print(f"ERROR: {error}.")
    print("Expected format:")
    print("  type(scope): summary")
    print_allowed_values()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
