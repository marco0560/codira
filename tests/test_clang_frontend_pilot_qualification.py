"""Test independent Clang pilot grading and immutable checkpoint behavior."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from scripts.clang_frontend_pilot.baseline_report import summarize_baseline
from scripts.clang_frontend_pilot.checkpoint import (
    append_attempt,
    can_skip_attempt,
    output_sha256,
)
from scripts.clang_frontend_pilot.cohort import (
    _identity_digest,
    _preprocessing_event_count,
    grade_cohort,
)
from scripts.clang_frontend_pilot.identity import CaseIdentity
from scripts.clang_frontend_pilot.measure import (
    _timing_summary,
    _verify_retained_inputs,
    run_batch,
)
from scripts.clang_frontend_pilot.qualification import (
    ExpectedFact,
    grade_fixture_facts,
    grade_record,
)


def test_fixture_grader_reports_missing_invented_and_duplicate_facts() -> None:
    """Compare frontend facts with a small hand-written source oracle.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    declaration = {
        "identity": {"kind": "written"},
        "qualified_name": "expected",
        "signature": "int expected(void)",
        "location": {
            "spelling": {"line": 1, "column": 5},
            "expansion": {"line": 1, "column": 5},
        },
    }

    call = {
        "origin": "source_written",
        "callee": {"name": "target"},
        "location": {
            "spelling": {"line": 2, "column": 8},
            "expansion": {"line": 2, "column": 8},
        },
    }
    invented = {
        "identity": {"kind": "written"},
        "qualified_name": "invented",
        "signature": "int invented(void)",
        "location": {
            "spelling": {"line": 3, "column": 5},
            "expansion": {"line": 3, "column": 5},
        },
    }
    record = {
        "frontend": {
            "declarations": [declaration, dict(declaration), invented],
            "calls": [call],
        }
    }
    expected = (
        ExpectedFact("declaration", "expected", 1, 5, "int expected(void)"),
        ExpectedFact("declaration", "missing", 4, 5, "int missing(void)"),
        ExpectedFact("call", "target", 2, 8, origin="source_written"),
    )

    grade = grade_fixture_facts(record, expected)

    assert grade.matched_count == 2
    assert not grade.passed
    assert Counter(issue.category for issue in grade.issues) == {
        "duplicate": 1,
        "missing": 1,
        "invented": 1,
    }


def test_batch_timing_summary_uses_only_finite_measured_runner_durations() -> None:
    """Summarize actual monotonic case timings and omit invalid samples.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    summary = _timing_summary(
        [
            {"runner_elapsed_seconds": 0.25},
            {"runner_elapsed_seconds": 0.5},
            {"runner_elapsed_seconds": True},
            {"runner_elapsed_seconds": float("nan")},
            {"status": "held"},
        ]
    )

    assert summary["timed_runner_count"] == 2
    assert summary["runner_wall_seconds_total"] == 0.75
    assert summary["runner_wall_seconds_median"] == 0.5
    assert summary["runner_wall_seconds_p95"] == 0.5


def test_preprocessing_count_handles_known_shapes_and_marks_unknown() -> None:
    """Count PP event arrays and keep unrecognized shapes explicit.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    assert _preprocessing_event_count([{"kind": "macro"}]) == 1
    assert _preprocessing_event_count({"events": [{"kind": "macro"}]}) == 1
    assert _preprocessing_event_count({"unexpected": []}) is None


def test_macro_spelling_and_expansion_coordinates_remain_distinct() -> None:
    """Require the macro body origin and physical invocation to both match.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    record = {
        "frontend": {
            "declarations": [],
            "calls": [
                {
                    "origin": "macro_replacement",
                    "site_identity": "fixture.c:91",
                    "expansion_identity": "fixture.c:141",
                    "callee": {"name": "helper"},
                    "location": {
                        "spelling": {
                            "path": "/fixture/macros.h",
                            "line": 4,
                            "column": 7,
                        },
                        "expansion": {
                            "path": "/fixture/fixture.c",
                            "line": 8,
                            "column": 3,
                        },
                    },
                }
            ],
        }
    }
    expected = (
        ExpectedFact(
            "call",
            "helper",
            8,
            3,
            origin="macro_replacement",
            spelling_line=4,
            spelling_column=7,
            expansion_line=8,
            expansion_column=3,
        ),
    )

    assert grade_fixture_facts(record, expected).passed
    wrong_spelling = (
        ExpectedFact(
            "call",
            "helper",
            8,
            3,
            origin="macro_replacement",
            spelling_line=8,
            spelling_column=3,
            expansion_line=8,
            expansion_column=3,
        ),
    )
    wrong_origin = (
        ExpectedFact(
            "call",
            "helper",
            8,
            3,
            origin="source_written",
            spelling_line=4,
            spelling_column=7,
            expansion_line=8,
            expansion_column=3,
        ),
    )
    assert not grade_fixture_facts(record, wrong_spelling).passed
    assert not grade_fixture_facts(record, wrong_origin).passed


def test_corpus_record_separates_native_acceptance_from_semantic_completeness(
    tmp_path: Path,
) -> None:
    """Coordinate-check extracted facts without making an ungraded claim.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the fixture source.

    Returns
    -------
    None
    """

    source_path = tmp_path / "fixture.c"
    source_path.write_bytes(b"int item(void);\n")
    record = {
        "status": "complete",
        "hold_reasons": [],
        "unmodeled_fields": ["attributes"],
        "frontend": {
            "declarations": [
                {
                    "identity": {"kind": "written"},
                    "qualified_name": "item",
                    "signature": "int item(void)",
                    "location": {
                        "spelling": {
                            "path": str(source_path),
                            "line": 1,
                            "column": 5,
                            "offset": 4,
                        },
                        "expansion": {
                            "path": str(source_path),
                            "line": 1,
                            "column": 5,
                            "offset": 4,
                        },
                    },
                }
            ],
            "calls": [],
            "diagnostics": [],
        },
    }

    grade = grade_record(record, source_path)

    assert grade.native_acceptance == "accepted"
    assert grade.semantic_completeness == "not_independently_graded"
    assert grade.extracted_fact_count == 1
    assert grade.coordinate_checked_count == 1
    assert grade.fully_verified_fact_count == 0
    assert grade.major_failure_counts["unmodeled:attributes"] == 1


def test_coordinate_ownership_splits_main_file_and_repository_header_facts(
    tmp_path: Path,
) -> None:
    """Count macro spelling and expansion owners independently.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository with one source and one included header.

    Returns
    -------
    None
    """

    repository_root = tmp_path / "repo"
    source_path = repository_root / "src" / "main.c"
    header_path = repository_root / "include" / "api.h"
    source_path.parent.mkdir(parents=True)
    header_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"int local(void);\nCALL(1);\n")
    header_path.write_bytes(b"int header(void);\n#define CALL(x) header(x)\n")
    source_start = {
        "path": str(source_path),
        "line": 1,
        "column": 5,
        "offset": 4,
    }
    header_start = {
        "path": str(header_path),
        "line": 1,
        "column": 5,
        "offset": 4,
    }
    source_call = {
        "path": str(source_path),
        "line": 2,
        "column": 1,
        "offset": 16,
    }
    macro_spelling = {
        "path": str(header_path),
        "line": 2,
        "column": 18,
        "offset": 35,
    }
    record = {
        "status": "complete",
        "hold_reasons": [],
        "unmodeled_fields": [],
        "frontend": {
            "declarations": [
                {
                    "identity": {"kind": "written"},
                    "name": "local",
                    "location": {"spelling": source_start, "expansion": source_start},
                },
                {
                    "identity": {"kind": "written"},
                    "name": "header",
                    "location": {"spelling": header_start, "expansion": header_start},
                },
            ],
            "calls": [
                {
                    "origin": "macro_replacement",
                    "callee": {"name": "header"},
                    "location": {
                        "spelling": macro_spelling,
                        "expansion": source_call,
                    },
                }
            ],
            "diagnostics": [],
        },
    }

    grade = grade_record(
        record,
        source_path,
        dependency_paths=(header_path,),
        repository_root=repository_root,
    )

    assert grade.fact_owner_counts == {"main_file": 2, "repository_header": 1}
    assert grade.spelling_owner_counts == {"main_file": 1, "repository_header": 2}
    assert grade.expansion_owner_counts == {"main_file": 2, "repository_header": 1}
    assert grade.coordinate_checked_count == 2


def test_unlocated_implicit_and_unbound_header_are_not_bad_coordinates(
    tmp_path: Path,
) -> None:
    """Separate synthetic rows and unavailable header bytes from bad claims.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source tree used for coordinate verification.

    Returns
    -------
    None
    """

    source_path = tmp_path / "main.c"
    source_path.write_bytes(b"int visible(void);\nvisible();\n")
    valid_declaration = {
        "path": str(source_path),
        "line": 1,
        "column": 5,
        "offset": 4,
    }
    valid_call = {
        "path": str(source_path),
        "line": 2,
        "column": 1,
        "offset": 19,
    }
    record = {
        "status": "complete",
        "frontend": {
            "declarations": [
                {
                    "identity": {"kind": "written"},
                    "name": "visible",
                    "location": {
                        "spelling": valid_declaration,
                        "expansion": valid_declaration,
                    },
                },
                {
                    "identity": {"kind": "implicit"},
                    "name": "__builtin_helper",
                    "location": {"spelling": None, "expansion": None},
                },
                {
                    "identity": {"kind": "written"},
                    "name": "header_decl",
                    "location": {
                        "spelling": {
                            "path": str(tmp_path / "unretained.h"),
                            "line": 900,
                            "column": 900,
                            "offset": 900,
                        },
                        "expansion": {
                            "path": str(tmp_path / "unretained.h"),
                            "line": 900,
                            "column": 900,
                            "offset": 900,
                        },
                    },
                },
            ],
            "calls": [
                {
                    "origin": "source_written",
                    "callee": {"name": "visible"},
                    "location": {
                        "spelling": valid_call,
                        "expansion": valid_call,
                    },
                },
                {
                    "origin": "builtin_or_synthetic",
                    "callee": {"name": "__builtin_helper"},
                    "location": {"spelling": None, "expansion": None},
                },
            ],
            "diagnostics": [],
        },
    }

    grade = grade_record(record, source_path)

    assert grade.issues == ()
    assert grade.coordinate_checked_count == 2
    assert grade.fact_owner_counts == {
        "external_or_unbound": 1,
        "main_file": 2,
        "unlocated_implicit_or_synthetic": 2,
    }


def test_written_main_file_coordinate_mismatch_is_rejected(tmp_path: Path) -> None:
    """Keep invalid coordinates strict for source-written main-file facts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source file used for coordinate verification.

    Returns
    -------
    None
    """

    source_path = tmp_path / "main.c"
    source_path.write_bytes(b"int visible(void);\n")
    incorrect = {
        "path": str(source_path),
        "line": 3,
        "column": 5,
        "offset": 4,
    }
    record = {
        "status": "complete",
        "frontend": {
            "declarations": [
                {
                    "identity": {"kind": "written"},
                    "name": "visible",
                    "location": {"spelling": incorrect, "expansion": incorrect},
                }
            ],
            "calls": [],
        },
    }

    grade = grade_record(record, source_path)

    assert grade.coordinate_checked_count == 0
    assert len(grade.issues) == 2
    assert all(issue.category == "coordinate" for issue in grade.issues)


def test_source_and_profile_changes_invalidate_checkpoint_reuse(tmp_path: Path) -> None:
    """Reuse only a complete artifact with the exact complete input identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory for the durable result record.

    Returns
    -------
    None
    """

    artifact = tmp_path / "result.ndjson"
    artifact.write_bytes(b'{"status":"complete"}\n')
    original = _identity(source="a", profile="b")
    attempt = {
        "status": "complete",
        "identity_sha256": original.digest(),
        "artifact_relpath": artifact.name,
        "artifact_sha256": output_sha256(artifact),
    }

    assert can_skip_attempt(attempt, original.digest(), tmp_path)
    assert not can_skip_attempt(
        attempt, _identity(source="c", profile="b").digest(), tmp_path
    )
    assert not can_skip_attempt(
        attempt, _identity(source="a", profile="d").digest(), tmp_path
    )


def test_contract_toolchain_hash_fields_produce_complete_case_identity() -> None:
    """Bind original driver, Clang compiler, helper, dependencies, and producer.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """

    digest = _sha256("contract component")
    record = {
        "source_sha256": _sha256("source"),
        "original_compile_command": {
            "driver": {"binary_sha256": digest},
            "arguments": ["c++", "-std=c++20", "case.cpp"],
        },
        "clang_adaptation": {
            "argv": ["-x", "c++", "-std=c++20"],
            "transformations": [],
            "unsupported_context": [],
            "toolchain": {
                "compiler_sha256": digest,
                "helper_sha256": digest,
            },
        },
        "dependency_closure": {"sha256": digest},
    }
    producer = {
        "adapter_runner_sha256": digest,
        "adapter_module_sha256": digest,
        "helper_sha256": digest,
        "configuration_sha256": digest,
    }

    identity = _identity_digest(record, producer)
    original_adaptation = record["clang_adaptation"]
    assert isinstance(original_adaptation, dict)
    changed_profile = {
        **record,
        "clang_adaptation": {
            **original_adaptation,
            "argv": ["-x", "c++", "-std=c++17"],
        },
    }

    assert identity is not None
    assert _identity_digest(changed_profile, producer) != identity


def test_failed_and_incomplete_attempts_are_retained_but_never_skipped(
    tmp_path: Path,
) -> None:
    """Keep raw failures in checkpoint history without treating them as success.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory containing retained raw output.

    Returns
    -------
    None
    """

    artifact = tmp_path / "failed.ndjson"
    artifact.write_bytes(b'{"status":"partial","diagnostic":"retained"}\n')
    identity = _identity(source="a", profile="b")
    failure = {
        "status": "failed",
        "identity_sha256": identity.digest(),
        "artifact_relpath": artifact.name,
        "artifact_sha256": output_sha256(artifact),
        "error": "compiler helper exited 1",
    }
    checkpoint = append_attempt({}, "case-1", failure)

    assert checkpoint["rows"] == {"case-1": [failure]}
    assert not can_skip_attempt(failure, identity.digest(), tmp_path)
    assert artifact.read_bytes().endswith(b'retained"}\n')


def test_resume_rejects_changed_original_compiler_binary(tmp_path: Path) -> None:
    """Use the contract's `binary_sha256` field when verifying reuse inputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary attempt and compiler file directory.

    Returns
    -------
    None
    """

    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"current compiler")
    raw = tmp_path / "repository" / "case" / "raw.ndjson"
    raw.parent.mkdir(parents=True)
    record = {
        "original_compile_command": {
            "driver": {
                "resolved_path": str(compiler),
                "binary_sha256": _sha256("different old compiler"),
            }
        },
        "dependency_closure": {"files": []},
    }
    raw.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="retained compiler changed"):
        _verify_retained_inputs(tmp_path)


def test_batch_resume_keeps_completed_output_and_incomplete_runner_logs(
    tmp_path: Path,
) -> None:
    """Resume exact completed rows and preserve interrupted process evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary adapter package, repository, and durable batch attempts.

    Returns
    -------
    None
    """

    repository = tmp_path / "repository"
    repository.mkdir()
    source_path = repository / "unit.c"
    source_path.write_text("int unit(void);\n", encoding="utf-8")
    revision = _make_git_repository(repository)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rows = [
        {
            "selection_id": "case-complete",
            "repository_id": "repo-one",
            "repository_revision": revision,
            "repository_relative_path": "unit.c",
            "source_sha256": source_sha,
        },
        {
            "selection_id": "case-incomplete",
            "repository_id": "repo-one",
            "repository_revision": revision,
            "repository_relative_path": "unit.c",
            "source_sha256": source_sha,
        },
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    compile_database = tmp_path / "compile_commands.json"
    compile_database.write_text("[]\n", encoding="utf-8")
    helper = tmp_path / "helper"
    helper.write_bytes(b"helper identity")
    runner = _write_fake_runner(tmp_path / "adapter-project")
    output_root = tmp_path / "measurement"
    mappings = {"repo-one": repository}
    compdbs = {"repo-one": compile_database}

    complete = run_batch(
        manifest,
        runner,
        helper,
        output_root,
        "resume-r1",
        mappings,
        compdbs,
        selection_ids=["case-complete"],
    )
    case_root = output_root / "attempts" / "resume-r1" / "repo-one" / "case-complete"
    raw_path = case_root / "raw.ndjson"
    original_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    resumed = run_batch(
        manifest,
        runner,
        helper,
        output_root,
        "resume-r1",
        mappings,
        compdbs,
        selection_ids=["case-complete"],
    )
    assert complete["status_counts"] == {"complete": 1}
    assert resumed["status_counts"] == {"complete": 1}
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == original_sha
    assert len(list((case_root / "invocations").glob("run-*"))) == 2

    failed = run_batch(
        manifest,
        runner,
        helper,
        output_root,
        "incomplete-r1",
        mappings,
        compdbs,
        selection_ids=["case-incomplete"],
    )
    failed_root = (
        output_root / "attempts" / "incomplete-r1" / "repo-one" / "case-incomplete"
    )
    assert failed["status_counts"] == {"incomplete": 1}
    assert any(
        path.read_text(encoding="utf-8") == "incomplete observation\n"
        for path in failed_root.rglob("runner.stdout.txt")
    )
    with pytest.raises(ValueError, match="incomplete retained case attempt"):
        run_batch(
            manifest,
            runner,
            helper,
            output_root,
            "incomplete-r1",
            mappings,
            compdbs,
            selection_ids=["case-incomplete"],
        )


def _make_git_repository(root: Path) -> str:
    """Create a committed source checkout for batch revision-binding tests.

    Parameters
    ----------
    root : pathlib.Path
        Repository directory containing a fixture source.

    Returns
    -------
    str
        Commit ID of the frozen fixture revision.

    Raises
    ------
    subprocess.CalledProcessError
        If Git cannot initialize or commit the fixture.
    """

    commands = (
        ("git", "init", "-q"),
        ("git", "config", "user.name", "Pilot Test"),
        ("git", "config", "user.email", "pilot@example.invalid"),
        ("git", "add", "unit.c"),
        ("git", "commit", "-q", "-m", "fixture"),
    )
    for command in commands:
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_fake_runner(root: Path) -> Path:
    """Write a tiny deterministic module stand-in for the adapter CLI.

    Parameters
    ----------
    root : pathlib.Path
        Temporary import root.

    Returns
    -------
    pathlib.Path
        Fake ``run.py`` module path.
    """

    package = root / "scripts" / "clang_frontend_pilot"
    package.mkdir(parents=True)
    (root / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "adapter.py").write_text("adapter identity\n", encoding="utf-8")
    (package / "contract.py").write_text("contract identity\n", encoding="utf-8")
    (package / "contract.md").write_text("contract docs\n", encoding="utf-8")
    runner = package / "run.py"
    runner.write_text(
        """import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
for name in ("manifest", "compile-commands", "repository-root", "helper", "output", "checkpoint", "selection-id"):
    parser.add_argument("--" + name, required=True)
args = parser.parse_args()
if args.selection_id == "case-incomplete":
    print("incomplete observation")
    raise SystemExit(17)
output = Path(args.output)
checkpoint = Path(args.checkpoint)
if not output.exists() and not checkpoint.exists():
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"selection_id": args.selection_id, "status": "complete", "context_status": "reproducible_profile", "hold_reasons": []}) + "\\n", encoding="utf-8")
    checkpoint.write_text(json.dumps({"selection_id": args.selection_id, "status": "complete"}) + "\\n", encoding="utf-8")
""",
        encoding="utf-8",
    )
    return runner


def test_cohort_grader_keeps_missing_profile_rows_in_file_coverage_denominator(
    tmp_path: Path,
) -> None:
    """Preserve an explicit held case and the full denominator in aggregation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source, manifest, and attempt root.

    Returns
    -------
    None
    """

    repository = tmp_path / "repo"
    source_path = repository / "one.c"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"int item(void);\n")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rows = [
        {
            "selection_id": "case-complete",
            "population_class": "llvm",
            "language": "c",
            "repository_id": "repo-one",
            "repository_revision": "rev-1",
            "repository_relative_path": "one.c",
            "source_sha256": source_sha,
            "classification_disposition": "investigate_and_fix",
            "feature_family": "declaration_call_template",
            "profile_context_status": "partial_profile",
        },
        {
            "selection_id": "case-held",
            "population_class": "nonllvm",
            "language": "cpp",
            "repository_id": "repo-one",
            "repository_revision": "rev-1",
            "repository_relative_path": "one.c",
            "source_sha256": source_sha,
            "classification_disposition": "investigate_and_fix",
            "feature_family": "preprocessor_context",
            "profile_context_status": "no_profile",
        },
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"schema_version": "test/1", "pilot_id": "pilot-test", "rows": rows}
        ),
        encoding="utf-8",
    )
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    attempt_root = tmp_path / "attempt"
    raw_path = attempt_root / "repo-one" / "case-complete" / "raw.ndjson"
    raw_path.parent.mkdir(parents=True)
    record = {
        "schema_version": "codira.clang-frontend-pilot-tu/1",
        "pilot_id": "pilot-test",
        "selection_id": "case-complete",
        "manifest_source": {
            "path": str(manifest_path.resolve()),
            "sha256": manifest_sha,
            "schema_version": "test/1",
        },
        "selection_row": rows[0],
        **rows[0],
        "status": "complete",
        "context_status": "partial_profile",
        "hold_reasons": [],
        "source_path": str(source_path),
        "frontend": {
            "declarations": [
                {
                    "identity": {"kind": "written"},
                    "qualified_name": "item",
                    "signature": "int item(void)",
                    "location": {
                        "spelling": {
                            "path": str(source_path),
                            "line": 1,
                            "column": 5,
                            "offset": 4,
                        },
                        "expansion": {
                            "path": str(source_path),
                            "line": 1,
                            "column": 5,
                            "offset": 4,
                        },
                    },
                }
            ],
            "calls": [],
            "preprocessing": [
                {"kind": "macro_definition"},
                {"kind": "conditional"},
            ],
            "diagnostics": [],
        },
        "dependency_closure": {"files": [], "sha256": _sha256("empty-dependencies")},
    }
    raw_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    attempt_root.mkdir(exist_ok=True)
    (attempt_root / "progress.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "selection_id": "case-held",
                        "status": "held",
                        "hold_reasons": [
                            "repository checkout or compilation database not supplied"
                        ],
                        "raw_artifact": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    baseline_root = tmp_path / "baseline-attempt"
    baseline_case = baseline_root / "cases" / "case-complete.json"
    baseline_case.parent.mkdir(parents=True)
    baseline_case.write_text(
        json.dumps(
            {
                "selection_id": "case-complete",
                "source_sha256_observed": source_sha,
                "baseline_tier": "default_analyzer_mode",
                "analyzer_name": "c",
                "analyzer_version": "23",
                "configuration_sha256": _sha256("default-config"),
                "runtime_identity": {"analyzer_source_revision": "11dcedac"},
                "run_status": "complete",
                "analysis_result": {
                    "index_symbols": False,
                    "status": {"coverage_state": "partial"},
                },
                "fact_counts": {"functions": 0, "declarations": 0, "calls": 0},
            }
        ),
        encoding="utf-8",
    )

    report = grade_cohort(
        manifest_path,
        attempt_root,
        {"repo-one": repository},
        default_baseline_root=baseline_root,
    )

    manifest_report = report["manifest"]
    summary = report["summary"]
    assert isinstance(manifest_report, dict)
    assert isinstance(summary, dict)
    assert manifest_report["cohort_denominator"] == 2
    assert summary["whole_file_supported_artifact_coverage"] == {
        "complete_files": 1,
        "selected_files": 2,
        "cohort_files": 2,
        "fraction_within_selected": 0.5,
        "fraction_of_cohort": 0.5,
    }
    assert summary["record_status_counts"] == {"complete": 1, "held": 1}
    assert summary["fully_verified_semantic_facts"] == 0
    report_rows = report["rows"]
    assert isinstance(report_rows, list)
    second_row = report_rows[1]
    assert isinstance(second_row, dict)
    assert second_row["semantic_completeness"] == "not_independently_graded"
    assert second_row["native_acceptance"] == "not_invoked"
    assert second_row["raw_output_state"] == "not_invoked_no_native_output_expected"
    assert second_row["issues"] == []
    assert summary["issue_counts"] == {}
    baseline_comparison = summary["baseline_comparison"]
    assert isinstance(baseline_comparison, dict)
    comparison = baseline_comparison["default_c23_cpp42"]
    assert isinstance(comparison, dict)
    comparison_rows = comparison["rows"]
    assert isinstance(comparison_rows, list)
    comparison_row = comparison_rows[0]
    assert isinstance(comparison_row, dict)
    assert comparison["paired_rows"] == 1
    assert comparison_row["input_context_relation"] == "different"
    interpretation = comparison_row["interpretation"]
    assert isinstance(interpretation, str)
    assert interpretation.startswith("side_by_side_measurement_only")
    clang_counts = comparison_row["clang"]["fact_counts"]
    assert isinstance(clang_counts, dict)
    assert clang_counts["preprocessing_events"] == 2

    smoke_report = grade_cohort(
        manifest_path,
        attempt_root,
        {"repo-one": repository},
        selected_ids=["case-complete"],
    )
    smoke_summary = smoke_report["summary"]
    assert isinstance(smoke_summary, dict)
    assert smoke_summary["selected_count"] == 1
    assert smoke_summary["unselected_count"] == 1
    assert smoke_summary["record_status_counts"] == {"complete": 1}
    assert smoke_summary["issue_counts"] == {}


def test_invoked_case_without_raw_envelope_remains_a_missing_error(
    tmp_path: Path,
) -> None:
    """Keep a missing envelope erroneous when the adapter invocation failed.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source, manifest, and progress evidence.

    Returns
    -------
    None
    """

    repository = tmp_path / "repo"
    source_path = repository / "case.c"
    repository.mkdir()
    source_path.write_bytes(b"int case_fn(void);\n")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    row = {
        "selection_id": "case-invoked-no-output",
        "population_class": "llvm",
        "language": "c",
        "repository_id": "repo-one",
        "repository_revision": "rev-1",
        "repository_relative_path": "case.c",
        "source_sha256": source_sha,
        "profile_context_status": "partial_profile",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "test/1", "rows": [row]}),
        encoding="utf-8",
    )
    attempt_root = tmp_path / "attempt"
    attempt_root.mkdir()
    (attempt_root / "progress.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "selection_id": row["selection_id"],
                        "status": "incomplete",
                        "hold_reasons": [
                            "adapter did not produce exactly one terminal envelope"
                        ],
                        "raw_artifact": None,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = grade_cohort(manifest_path, attempt_root, {"repo-one": repository})

    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["issue_counts"] == {"missing": 1}
    rows = report["rows"]
    assert isinstance(rows, list)
    result = rows[0]
    assert isinstance(result, dict)
    assert result["native_acceptance"] == "not_established"
    assert result["raw_output_state"] == "missing_after_invocation"
    assert result["issues"] == [
        {
            "category": "missing",
            "fact": "no raw terminal envelope after adapter invocation",
        }
    ]


def test_baseline_report_counts_dto_lines_columns_and_methods(tmp_path: Path) -> None:
    """Count actual Codira DTO span keys, excluding status diagnostics.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary manifest and baseline record directory.

    Returns
    -------
    None
    """

    row = {
        "selection_id": "case-coordinate-dto",
        "profile_context_status": "no_profile",
        "source_sha256": _sha256("source"),
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"rows": [row]}), encoding="utf-8")
    attempt_root = tmp_path / "attempt"
    case_path = attempt_root / "cases" / "case-coordinate-dto.json"
    case_path.parent.mkdir(parents=True)
    case_path.write_text(
        json.dumps(
            {
                **row,
                "run_status": "complete",
                "analysis_elapsed_seconds": 0.25,
                "source_sha256_observed": row["source_sha256"],
                "repository_head": "revision",
                "analysis_result": {
                    "index_symbols": True,
                    "functions": [
                        {
                            "lineno": 2,
                            "end_lineno": 3,
                            "calls": [{"lineno": 3, "col_offset": 10}],
                        }
                    ],
                    "classes": [
                        {
                            "lineno": 1,
                            "methods": [{"lineno": 4, "end_lineno": 5, "calls": []}],
                        }
                    ],
                    "declarations": [{"lineno": 1}],
                    "imports": [],
                    "documentation": [{"lineno": 1}],
                    "status": {
                        "coverage_state": "partial",
                        "diagnostics": [{"line": 1, "column": 2}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    report = summarize_baseline(manifest, attempt_root)

    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["fact_count_totals"] == {
        "calls": 1,
        "classes": 1,
        "declarations": 1,
        "documentation": 1,
        "functions_and_methods": 2,
        "imports": 0,
        "modules": 1,
    }
    assert summary["source_coordinate_totals"] == {
        "source_column_objects": 1,
        "source_end_line_objects": 2,
        "source_line_objects": 6,
    }
    assert summary["timed_case_count"] == 1
    assert summary["case_analysis_elapsed_seconds_total"] == 0.25
    timing_basis = summary["timing_basis"]
    assert isinstance(timing_basis, str)
    assert timing_basis.startswith("monotonic timer")


def _identity(source: str, profile: str) -> CaseIdentity:
    """Build a test identity with independently variable source and profile.

    Parameters
    ----------
    source : str
        One ASCII discriminator for source bytes.
    profile : str
        One ASCII discriminator for compile-profile bytes.

    Returns
    -------
    CaseIdentity
        Complete deterministic identity with six SHA-256 components.
    """

    return CaseIdentity(
        source_sha256=_sha256(source),
        profile_sha256=_sha256(profile),
        dependency_sha256=_sha256("dependencies"),
        compiler_sha256=_sha256("compiler"),
        producer_sha256=_sha256("producer"),
        configuration_sha256=_sha256("configuration"),
    )


def _sha256(value: str) -> str:
    """Hash one test discriminator as UTF-8 bytes.

    Parameters
    ----------
    value : str
        Test identity discriminator.

    Returns
    -------
    str
        SHA-256 digest.
    """

    import hashlib

    return hashlib.sha256(value.encode("ascii")).hexdigest()
