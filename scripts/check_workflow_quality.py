#!/usr/bin/env python3
"""Collect inexpensive repository quality failures before the full gate.

Parameters
----------
None

Returns
-------
None
    Reuses the authoritative validator without replacing its full gate.
"""

from __future__ import annotations

import argparse
import json
import sys

if __package__ in {None, ""}:
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_repo import (
    RUN_REPO_TOOL,
    VALIDATION_STEPS,
    build_validation_commands,
    run_validation,
)

QUALITY_STEPS = frozenset(
    {"ruff", "ruff-format", "mypy", "mypy-packages", "semgrep", "docstring-audit"}
)


def main(arguments: list[str] | None = None) -> int:
    """Refresh the index and report every inexpensive validation failure.

    Parameters
    ----------
    arguments : list[str] or None, optional
        CLI arguments; ``--dry-run`` prints commands without executing them.

    Returns
    -------
    int
        Zero if the selected checks pass, otherwise one. A failed index refresh
        marks the audit unavailable rather than querying stale definitions.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args(arguments)
    checks: list[tuple[str, tuple[str, ...]]] = [
        ("index-refresh", (sys.executable, str(RUN_REPO_TOOL), "codira", "index"))
    ]
    checks.extend(
        (step.name, command)
        for step, command in zip(
            VALIDATION_STEPS, build_validation_commands(), strict=True
        )
        if step.name in QUALITY_STEPS
    )
    results: dict[str, int | None] = {}
    for name, command in checks:
        if options.dry_run:
            print(json.dumps({"check": name, "command": command}))
        elif name == "docstring-audit" and results["index-refresh"] != 0:
            results[name] = None
        else:
            results[name] = run_validation((command,))
    print(json.dumps({"quality_checks": results, "full_gate_required": True}))
    return int(any(status != 0 for status in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
