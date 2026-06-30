#!/usr/bin/env python3
"""Execute arguments through the repository Python interpreter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import resolve_python


def main(argv: list[str] | None = None) -> int:
    """
    Execute Python arguments through the resolved repository interpreter.

    Parameters
    ----------
    argv : list[str] | None, optional
        Arguments for the Python interpreter. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Child process exit status.
    """

    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(
            "Usage: scripts/run_with_repo_python.py <python-args...>", file=sys.stderr
        )
        return 1
    return subprocess.call([resolve_python(), *args])


if __name__ == "__main__":
    raise SystemExit(main())
