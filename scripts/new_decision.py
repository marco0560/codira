#!/usr/bin/env python3
"""Create a new ADR note under docs/adr.

Responsibilities
----------------
- Prompt for a one-line description, slugify it deterministically, and select the next incremental ADR number.
- Author the Markdown decision template and append an entry to the ADR index, respecting dry-run options.
- Exit with descriptive errors when the ADR directory or index file is missing.

Design principles
-----------------
The helper avoids heuristics, keeps the ADR template minimal, and relies on deterministic slugification plus explicit failure modes.

Architectural role
------------------
This script belongs to the **decision tooling layer** and keeps repository-level architecture decisions documented consistently.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_DECISIONS_DIR = Path("docs/adr")
INDEX_FILENAME = "index.md"
STOPWORDS = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "to",
    "for",
    "in",
    "on",
    "with",
    "by",
}


def slugify(text: str) -> str:
    """
    Convert a one-line description into a filesystem-friendly slug.

    Parameters
    ----------
    text : str
        One-line ADR description.

    Returns
    -------
    str
        Lowercase ASCII slug suitable for an ADR filename.

    Raises
    ------
    ValueError
        If the supplied text cannot be converted into a usable slug.
    """

    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized).lower()
    tokens = [token for token in normalized.split() if token not in STOPWORDS]
    if not tokens:
        msg = "Description does not produce a valid slug"
        raise ValueError(msg)
    return "-".join(tokens)


def next_decision_number(decisions_dir: Path) -> int:
    """
    Return the next numeric ADR prefix.

    Parameters
    ----------
    decisions_dir : pathlib.Path
        Directory containing ADR markdown files.

    Returns
    -------
    int
        Next available ADR number.
    """

    numbers = []
    for path in decisions_dir.glob("ADR-*.md"):
        match = re.match(r"ADR-(\d+)-", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def fail(message: str) -> None:
    """
    Print an error and exit.

    Parameters
    ----------
    message : str
        Error message to emit.

    Returns
    -------
    None
        This function does not return.
    """

    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    """
    Create a new ADR note and update the ADR index.

    Parameters
    ----------
    argv : list[str] | None, optional
        Optional command-line argument override.

    Returns
    -------
    int
        Process exit code.
    """

    parser = argparse.ArgumentParser(description="Create a new ADR note.")
    parser.add_argument("--decisions-dir", type=Path, default=DEFAULT_DECISIONS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    decisions_dir = args.decisions_dir
    index_file = decisions_dir / INDEX_FILENAME
    if not decisions_dir.is_dir():
        fail(f"ADR directory not found: {decisions_dir}")
    if not index_file.is_file():
        fail(f"ADR index not found: {index_file}")

    description = input("One-line ADR description: ").strip()
    if not description:
        fail("Description cannot be empty")

    decision_number = next_decision_number(decisions_dir)
    filename = f"ADR-{decision_number:03d}-{slugify(description)}.md"
    target = decisions_dir / filename
    content = f"""# ADR-{decision_number:03d} — {description}

**Date:** {dt.date.today().strftime("%d/%m/%Y")}
**Status:** Accepted

## Context

<Describe the context>

## Decision

<Describe the decision>

## Consequences

<Describe the consequences>
"""
    index_entry = f"- [ADR-{decision_number:03d} — {description}]({filename})\n"

    print(f"ADR file: {target}")
    if args.dry_run:
        return 0

    target.write_text(content, encoding="utf-8")
    with index_file.open("a", encoding="utf-8") as handle:
        handle.write(index_entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
