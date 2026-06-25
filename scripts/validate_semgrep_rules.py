"""Validate repository-owned Semgrep fixture expectations.

Responsibilities
----------------
- Run Semgrep against fixture targets that intentionally violate repository
  rules.
- Confirm each expected rule identifier is emitted for the matching fixture
  surface.

Design principles
-----------------
Validation stays lightweight and deterministic by running repository-owned
Semgrep rules through the existing wrapper script.

Architectural role
------------------
This module belongs to the **development tooling layer** and protects the
repository's Semgrep rule contract.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_REPO_TOOL = REPO_ROOT / "scripts" / "run_repo_tool.py"

FIXTURES = (
    (
        "architecture",
        "fixtures/packages",
        (
            "codira.arch.no-storage-import-in-analyzers",
            "codira.arch.no-registry-import-in-analyzers",
            "codira.arch.no-sqlite3-in-analyzers",
            "codira.arch.no-backend-import-in-analyzers",
            "codira.arch.require-analyzer-capability-declaration",
            "codira.plugins.no-core-storage-import",
        ),
    ),
    (
        "architecture-core",
        "fixtures/src",
        (
            "codira.arch.no-sqlite3-outside-allowed-layers",
            "codira.arch.no-backend-package-import-outside-allowed-layers",
        ),
    ),
    (
        "architecture-duckdb",
        "fixtures/packages/codira-backend-duckdb",
        (
            "codira.arch.no-duckdb-executemany-in-support",
            "codira.arch.no-duckdb-returning-id-in-support",
        ),
    ),
    (
        "plugins",
        "fixtures/packages",
        (
            "codira.plugins.no-broad-except-exception",
            "codira.plugins.require-shared-plugin-json-schema-helper",
        ),
    ),
    (
        "determinism",
        "fixtures/src",
        ("codira.det.no-random-without-explicit-seed",),
    ),
)


def run_fixture(
    name: str,
    target: str,
    rule_ids: tuple[str, ...],
) -> int:
    """
    Run one Semgrep fixture scan and verify the expected rules fire.

    Parameters
    ----------
    name : str
        Short fixture label printed in validation output.
    target : str
        Repository-relative fixture path passed to Semgrep.
    rule_ids : tuple[str, ...]
        Rule identifiers that must appear in the scan output.

    Returns
    -------
    int
        ``0`` when every expected rule appears, otherwise ``1``.
    """
    command = (
        sys.executable,
        str(RUN_REPO_TOOL),
        "semgrep",
        "scan",
        "--config",
        str(REPO_ROOT / "semgrep" / "rules"),
        "--metrics=off",
        "--disable-version-check",
        "--json",
        target,
    )

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    output = f"{result.stdout}\n{result.stderr}"

    for rule_id in rule_ids:
        if rule_id not in output:
            print(f"[FAIL] {name}: expected rule not triggered: {rule_id}")
            return 1

    print(f"[OK] {name}")
    return 0


def main() -> int:
    """
    Validate every repository-owned Semgrep fixture group.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit status for the fixture validation run.
    """
    failures = 0

    for name, target, rule_ids in FIXTURES:
        failures += run_fixture(name, target, rule_ids)

    if failures:
        print(f"[FAIL] {failures} Semgrep fixture checks failed")
        return 1

    print("[OK] all Semgrep fixture checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
