#!/usr/bin/env python3
"""Codira to Codex bridge that turns natural-language queries into deterministic prompts.

Responsibilities
----------------
- Parse command-line arguments, forward the user query to `codira ctx --prompt`, and print the resulting prompt.
- Display usage guidance when invoked without arguments or with help flags.
- Surface errors and exit codes from codira so automation can react predictably.

Design principles
-----------------
The wrapper keeps invocation deterministic, exposes only plain-text prompts, and avoids embedding complex logic beyond glue.

Architectural role
------------------
This module belongs to the **tooling layer** that connects codira context with Codex-style automation workflows.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

CODIRA_EXE = shutil.which("codira") or "codira"


def _print_help() -> None:
    """
    Print command usage for ``ri-fix``.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Help text is written to standard output.
    """
    print("Usage: ri-fix <query>")
    print()
    print("Wrapper for: codira ctx --prompt <query>")
    print()
    print("Example:")
    print(
        '  ri-fix "Use codira to find where ctx builds the prompt '
        'and add a regression test"'
    )


def main() -> None:
    """
    Forward a natural-language query to ``codira ctx --prompt``.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The generated prompt is printed to standard output.

    Raises
    ------
    SystemExit
        If no query arguments are provided or the underlying ``codira``
        command exits with a non-zero status.
    """
    if len(sys.argv) >= 2 and sys.argv[1] in {"-h", "--help"}:
        _print_help()
        sys.exit(0)

    if len(sys.argv) < 2:
        _print_help()
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    try:
        result = subprocess.run(
            [CODIRA_EXE, "ctx", query, "--prompt"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print(exc.stderr)
        sys.exit(exc.returncode)

    print(result.stdout)


if __name__ == "__main__":
    main()
