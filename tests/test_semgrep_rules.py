"""Tests for repository-owned Semgrep rule assets.

Responsibilities
----------------
- Keep the Semgrep fixture inventory aligned with the repository rule set.
- Validate that Semgrep rule files remain parseable YAML documents.
- Protect the fixture-validation helper contract from drifting out of sync.

Design principles
-----------------
These tests stay structural and deterministic so Semgrep asset regressions fail
without depending on unsupported upstream test-layout features.

Architectural role
------------------
This module belongs to the **verification layer** for repository-owned Semgrep
guardrails.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:

    class _SemgrepValidationModule(Protocol):
        FIXTURES: tuple[tuple[str, str, tuple[str, ...]], ...]


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_REPO_TOOL = REPO_ROOT / "scripts" / "run_repo_tool.py"
SEMgrep_RULE_DIR = REPO_ROOT / "semgrep" / "rules"
FIXTURE_FILES = (
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "analyzer_backend_import_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "analyzer_missing_capability_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "analyzer_registry_import_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "analyzer_sqlite_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "analyzer_storage_import_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-analyzer-test"
    / "src"
    / "plugin_broad_except_exception_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-embedding-test"
    / "src"
    / "plugin_manual_schema_violation.py",
    REPO_ROOT / "fixtures" / "src" / "core_backend_import_violation.py",
    REPO_ROOT / "fixtures" / "src" / "core_sqlite_outside_allowlist_violation.py",
    REPO_ROOT / "fixtures" / "src" / "query_config_resolution_violation.py",
    REPO_ROOT / "fixtures" / "src" / "random_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-backend-duckdb"
    / "src"
    / "full_index_bulk_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-backend-duckdb"
    / "src"
    / "duckdb_support_batch_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-vector-store-duckdb"
    / "src"
    / "vector_store_batch_violation.py",
    REPO_ROOT
    / "fixtures"
    / "packages"
    / "codira-vector-store-duckdb"
    / "src"
    / "vector_store_full_index_violation.py",
)
EXPECTED_FIXTURE_RULE_IDS = {
    "codira.arch.no-backend-import-in-analyzers",
    "codira.arch.no-backend-package-import-outside-allowed-layers",
    "codira.arch.no-direct-config-load-in-query-hot-path",
    "codira.arch.no-duckdb-executemany-in-support",
    "codira.arch.no-duckdb-returning-id-in-support",
    "codira.arch.no-store-analysis-in-duckdb-full-index-bulk",
    "codira.arch.no-core-schema-ddl-import-in-backends",
    "codira.arch.require-fresh-full-index-embedding-flush",
    "codira.arch.no-vector-store-normal-path-in-duckdb-full-index-bulk",
    "codira.arch.no-registry-import-in-analyzers",
    "codira.arch.no-sqlite3-in-analyzers",
    "codira.arch.no-sqlite3-outside-allowed-layers",
    "codira.arch.no-storage-import-in-analyzers",
    "codira.arch.require-analyzer-capability-declaration",
    "codira.det.no-random-without-explicit-seed",
    "codira.plugins.no-broad-except-exception",
    "codira.plugins.no-core-storage-import",
    "codira.plugins.require-shared-plugin-json-schema-helper",
}


def _load_semgrep_validation_helper() -> _SemgrepValidationModule:
    """
    Load the Semgrep fixture validation helper from its repository path.

    Parameters
    ----------
    None

    Returns
    -------
    object
        Loaded module object for the Semgrep fixture validation helper.
    """

    helper_path = REPO_ROOT / "scripts" / "validate_semgrep_rules.py"
    spec = spec_from_file_location("validate_semgrep_rules", helper_path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_SemgrepValidationModule", module)


def test_semgrep_rule_files_are_valid_yaml(tmp_path: Path) -> None:
    """
    Keep repository-owned Semgrep rules accepted by the Semgrep CLI.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory used as an empty Semgrep scan target.

    Returns
    -------
    None
        The test asserts every Semgrep rule file is accepted by a Semgrep scan
        against an empty target directory.
    """

    scan_root = tmp_path / "scan-root"
    scan_root.mkdir()
    for path in sorted(SEMgrep_RULE_DIR.glob("*.yml")):
        completed = subprocess.run(
            (
                sys.executable,
                str(RUN_REPO_TOOL),
                "semgrep",
                "scan",
                "--config",
                str(path),
                "--metrics=off",
                "--disable-version-check",
                str(scan_root),
            ),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout


def test_semgrep_fixture_inventory_is_present() -> None:
    """
    Keep the Semgrep fixture corpus aligned with the current rule coverage.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the expected violating fixture files exist.
    """

    missing = [path for path in FIXTURE_FILES if not path.exists()]
    assert missing == []


def test_semgrep_fixture_validator_covers_expected_rule_ids() -> None:
    """
    Keep fixture validation coverage aligned with the rule inventory.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the fixture-validation helper references the expected
        Semgrep rule identifiers.
    """

    helper = _load_semgrep_validation_helper()
    actual_rule_ids = {
        rule_id for _name, _target, rule_ids in helper.FIXTURES for rule_id in rule_ids
    }
    assert actual_rule_ids == EXPECTED_FIXTURE_RULE_IDS
