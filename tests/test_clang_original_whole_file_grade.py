"""Contract checks for bound whole-file grade inputs."""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import codira_analyzer_c
import codira_clang_frontend
import pytest

import scripts.clang_original_whole_file_grade as grader
from scripts.clang_original_whole_file_grade import (
    SOURCE_FACT_CATEGORIES,
    GradeRequest,
    SourceOwnedAstGradeRequest,
    _canonical,
    _database_generation_binding,
    _read_actual_analysis_status,
    _source_literal_includes,
    _validate_compile_database_row,
    _validate_contract_header,
    _validate_extractor_domain,
    _validate_indexed_context_identity,
    _validate_normalized_site_accounting,
    _validate_persisted_clang_identity,
    _validate_persisted_status_claims,
    _validate_profile_identity_pair,
    _validate_receipt_database_binding,
    _validate_required_reference_coverage,
    _validate_source_fact_accounting,
    _validate_source_key,
    grade_contract,
    grade_source_owned_ast_categories,
    grade_source_owned_ast_evidence,
)
from scripts.clang_parity_qualification import (
    FACT_CATEGORIES,
    OracleFormatError,
    _source_macro_invocation_span,
)
from scripts.clang_reference_facts import REQUIRED_CATEGORIES, normalize_ast

if TYPE_CHECKING:
    from codira_clang_frontend.contracts import CompileProfile

    from scripts.clang_parity_qualification import JSONValue


def _generation_binding(backend: str) -> dict[str, JSONValue]:
    """Return a realistic persisted index-generation identity."""
    return {
        "backend": backend,
        "database_path": f"/indexes/{backend}.db",
        "database_sha256": f"{backend}-database-hash",
        "generation": 7,
        "generation_sha256": f"{backend}-generation-hash",
        "metadata_sha256": f"{backend}-metadata-hash",
        "analysis_fingerprint": f"{backend}-analysis-fingerprint",
        "analyzer_inventory": [{"name": "cpp", "version": "49"}],
        "schema_version": "29",
        "git_commit": "source-revision",
    }


def _receipt(backend: str, binding: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Return one backend receipt with its exact generation object."""
    section_name = "index" if backend == "sqlite" else "duckdb"
    backend_key = "backend" if backend == "sqlite" else "backend_name"
    section = {
        backend_key: backend,
        "database_path": binding["database_path"],
        "database_sha256": binding["database_sha256"],
        "generation_sha256": binding["generation_sha256"],
        "metadata_sha256": binding["metadata_sha256"],
        "schema_version": binding["schema_version"],
        "generation": {
            "generation": binding["generation"],
            "analysis_fingerprint": binding["analysis_fingerprint"],
            "analyzer_inventory": binding["analyzer_inventory"],
            "git_commit": binding["git_commit"],
        },
    }
    return {section_name: section}


def test_real_generation_domain_pair_accepts_distinct_profile_and_context() -> None:
    """Accept CFP-067's persisted profile and frontend-context identities.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    bindings: dict[str, JSONValue] = {
        "profile_identity": "9568384262185c4cb32a09313e052b5732a8c368bc2f51bc17b18fc007658f7f",
        "analysis_context_identity": "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8",
    }
    _validate_profile_identity_pair(
        bindings,
        "9568384262185c4cb32a09313e052b5732a8c368bc2f51bc17b18fc007658f7f",
        "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8",
    )


@pytest.mark.parametrize(
    "wrong_profile_identity",
    [
        "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8",
        "e4db988946756c37d08d9ce36bd750f913a17f99ead44eb509a6bb78f024eb59",
    ],
)
def test_wrong_fingerprint_domain_cannot_replace_profile_identity(
    wrong_profile_identity: str,
) -> None:
    """Reject context and fallback fingerprints supplied as profile identity.

    Parameters
    ----------
    wrong_profile_identity : str
        Incorrect fingerprint used to challenge the profile identity check.

    Returns
    -------
    None
    """
    bindings: dict[str, JSONValue] = {
        "profile_identity": "9568384262185c4cb32a09313e052b5732a8c368bc2f51bc17b18fc007658f7f",
        "analysis_context_identity": "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8",
    }
    with pytest.raises(OracleFormatError, match="profile_identity"):
        _validate_profile_identity_pair(
            bindings,
            wrong_profile_identity,
            "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8",
        )


def test_ast_dump_and_fresh_normalizer_extractor_hashes_are_separate() -> None:
    """Accept a fresh normalizer when its inventory binds that exact version.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    _validate_extractor_domain(
        "historical-dump-extractor",
        "frozen-current-normalizer",
        "frozen-current-normalizer",
    )


def test_source_inventory_cannot_claim_ast_dump_extractor_as_normalizer() -> None:
    """Reject an inventory built by an extractor different from its receipt.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    with pytest.raises(OracleFormatError, match="fresh normalizer"):
        _validate_extractor_domain(
            "historical-dump-extractor",
            "frozen-current-normalizer",
            "historical-dump-extractor",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_generation",
        "same_source_wrong_database",
        "missing_generation_sha",
        "missing_metadata_sha",
        "missing_schema",
    ],
)
def test_backend_receipt_must_match_database_generation(
    mutation: str,
) -> None:
    """Reject stale or mismatched database bindings for the same source.

    Parameters
    ----------
    mutation : str
        Database-receipt field mutation to reject.

    Returns
    -------
    None
    """
    binding = _generation_binding("sqlite")
    receipt = _receipt("sqlite", binding)
    section = cast("dict[str, JSONValue]", receipt["index"])
    if mutation == "stale_generation":
        generation = cast("dict[str, JSONValue]", section["generation"])
        generation["generation"] = 6
    else:
        if mutation == "same_source_wrong_database":
            section["database_path"] = "/indexes/duckdb.db"
        elif mutation == "missing_generation_sha":
            del section["generation_sha256"]
        elif mutation == "missing_metadata_sha":
            del section["metadata_sha256"]
        else:
            del section["schema_version"]
    with pytest.raises(OracleFormatError):
        _validate_receipt_database_binding(receipt, "sqlite", binding)


def test_backend_receipt_must_match_analysis_fingerprint() -> None:
    """Reject a receipt from another source-analysis generation.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    binding = _generation_binding("duckdb")
    receipt = _receipt("duckdb", binding)
    section = cast("dict[str, JSONValue]", receipt["duckdb"])
    generation = cast("dict[str, JSONValue]", section["generation"])
    generation["analysis_fingerprint"] = "different-fingerprint"
    with pytest.raises(OracleFormatError, match="analysis_fingerprint"):
        _validate_receipt_database_binding(receipt, "duckdb", binding)


def test_indexed_target_context_carries_current_frontend_fingerprint() -> None:
    """Check nested frontend identity independently of backend fingerprints.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    frontend_identity = (
        "b5fe48ed40f6b1fcf8386178b80507b67e91b9539a911d284741c548bda0ddb8"
    )
    context = json.dumps(
        {
            "clang_frontend_fingerprint": frontend_identity,
            "configuration_fingerprint": "backend-specific-inputs",
            "format": 1,
        }
    )
    _validate_indexed_context_identity("sqlite", context, frontend_identity)
    with pytest.raises(OracleFormatError, match="frontend fingerprint"):
        _validate_indexed_context_identity("duckdb", context, "wrong-context")


def test_compile_database_profile_argv_mismatch_is_rejected(tmp_path: Path) -> None:
    """Reject profile arguments that differ from the selected CDB row.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the source and compile database.

    Returns
    -------
    None
    """
    source = tmp_path / "unit.cpp"
    source.write_text("int value;\n", encoding="utf-8")
    workdir = tmp_path / "build"
    workdir.mkdir()
    compile_database = tmp_path / "compile_commands.json"
    compile_database.write_text(
        json.dumps(
            [
                {
                    "directory": str(workdir),
                    "file": str(source),
                    "arguments": ["/usr/bin/c++", "-DVALUE=1", "-c", str(source)],
                }
            ]
        ),
        encoding="utf-8",
    )
    profile = cast(
        "CompileProfile",
        SimpleNamespace(
            working_directory=str(workdir),
            argv=("/usr/bin/c++", "-DVALUE=2", "-c", str(source)),
        ),
    )
    with pytest.raises(
        OracleFormatError, match="does not match the captured profile argv"
    ):
        _validate_compile_database_row(compile_database, profile, source)


def _normalized_fixture() -> dict[str, JSONValue]:
    """Return normalized facts with no ungraded candidates."""
    return cast(
        "dict[str, JSONValue]",
        {
            "facts": {"calls": [{"offset": 8, "name": "run"}], "types": []},
            "ungraded_counts": {},
            "whole_file_parity": True,
            "required_category_coverage": {
                category: {"status": "graded"} for category in REQUIRED_CATEGORIES
            },
        },
    )


def _site_inventory(normalized: dict[str, JSONValue]) -> dict[str, JSONValue]:
    """Return complete site accounting for a normalized fixture."""
    facts = cast("dict[str, list[JSONValue]]", normalized["facts"])
    rows: list[JSONValue] = []
    source_facts: list[JSONValue] = []
    normalized_to_oracle_category = {
        "callables": "callables",
        "calls": "calls",
        "declarations": "declarations",
        "fields": "fields",
        "source_call_sites": "calls",
        "types": "types",
    }
    for category, values in facts.items():
        for ordinal, fact in enumerate(values):
            fact_digest = hashlib.sha256(_canonical(fact).encode("utf-8")).hexdigest()
            source_category = normalized_to_oracle_category.get(category, category)
            site_id = f"{source_category}:{ordinal}"
            rows.append(
                {
                    "category": category,
                    "ordinal": ordinal,
                    "site_id": site_id,
                    "disposition": "expected",
                    "basis": "independently reconciled source site",
                    "fact_sha256": fact_digest,
                    "source_fact_link": {
                        "category": source_category,
                        "ordinal": ordinal,
                        "fact_sha256": fact_digest,
                    },
                }
            )
            source_facts.append(
                {
                    "category": source_category,
                    "ordinal": ordinal,
                    "site_id": site_id,
                    "fact_sha256": fact_digest,
                }
            )
    return cast(
        "dict[str, JSONValue]",
        {
            "source_fact_accounting": source_facts,
            "normalized_site_accounting": {"rows": rows, "ungraded_dispositions": []},
        },
    )


def test_normalized_site_accounting_accepts_exact_complete_mapping() -> None:
    """Accept a one-to-one inventory for every normalized source-site row.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    normalized = _normalized_fixture()
    _validate_normalized_site_accounting(_site_inventory(normalized), normalized)


@pytest.mark.parametrize(
    "mutation",
    [
        "dropped",
        "extra",
        "duplicate",
        "unmapped",
        "wrong_digest",
        "excluded",
        "wrong_site_link",
    ],
)
def test_normalized_site_accounting_rejects_non_bijective_mapping(
    mutation: str,
) -> None:
    """Reject dropped, invented, duplicated, unmapped, or stale fact rows.

    Parameters
    ----------
    mutation : str
        Accounting mutation applied before validation.

    Returns
    -------
    None
    """
    normalized = _normalized_fixture()
    inventory = _site_inventory(normalized)
    accounting = cast("dict[str, JSONValue]", inventory["normalized_site_accounting"])
    rows = cast("list[JSONValue]", accounting["rows"])
    if mutation == "dropped":
        rows.pop(0)
    elif mutation == "extra":
        rows.append(
            {
                "category": "calls",
                "ordinal": 99,
                "site_id": "extra",
                "disposition": "expected",
                "basis": "extra",
                "fact_sha256": "x",
            }
        )
    elif mutation == "duplicate":
        rows.append(dict(cast("dict[str, JSONValue]", rows[0])))
    elif mutation == "unmapped":
        cast("dict[str, JSONValue]", rows[0])["category"] = "unknown"
    elif mutation == "wrong_digest":
        cast("dict[str, JSONValue]", rows[0])["fact_sha256"] = "stale"
    elif mutation == "excluded":
        cast("dict[str, JSONValue]", rows[0])["disposition"] = "excluded"
    else:
        cast("dict[str, JSONValue]", rows[0])["source_fact_link"] = {
            "category": "calls",
            "ordinal": 9,
        }
    with pytest.raises(OracleFormatError):
        _validate_normalized_site_accounting(inventory, normalized)


def test_normalized_site_accounting_keeps_ungraded_capture_held() -> None:
    """Reject a capture that reports unresolved AST categories.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    normalized = _normalized_fixture()
    normalized["ungraded_counts"] = {"implicit_declaration": 1}
    inventory = _site_inventory(normalized)
    accounting = cast("dict[str, JSONValue]", inventory["normalized_site_accounting"])
    accounting["ungraded_dispositions"] = [
        {
            "reason": "implicit_declaration",
            "count": 1,
            "disposition": "held",
            "basis": "not mapped",
        }
    ]
    with pytest.raises(
        OracleFormatError, match="keeps AST-based whole-file grading held"
    ):
        _validate_normalized_site_accounting(inventory, normalized)


def test_required_reference_coverage_rejects_unknown_or_partial_statuses() -> None:
    """Accept only known, complete coverage statuses for every category.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    coverage: dict[str, JSONValue] = {
        category: {
            "status": "accepted_with_diagnostics"
            if category == "native_parse_and_diagnostics"
            else "accepted"
        }
        for category in REQUIRED_CATEGORIES
    }
    _validate_required_reference_coverage(coverage)
    cast("dict[str, JSONValue]", coverage["template_and_implicit_declarations"])[
        "status"
    ] = "probably_complete"
    with pytest.raises(OracleFormatError, match="remains incomplete"):
        _validate_required_reference_coverage(coverage)


def test_source_fact_accounting_reconciles_oracle_with_source_bytes(
    tmp_path: Path,
) -> None:
    """Bind every source fact to its exact physical source coordinate.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for source and inventory fixtures.

    Returns
    -------
    None
    """
    facts: dict[str, JSONValue] = {category: [] for category in SOURCE_FACT_CATEGORIES}
    fact_rows: list[JSONValue] = [
        {"line": 1, "name": "run"},
        {"line": 2, "name": "stop"},
    ]
    facts["callables"] = fact_rows
    source_path = tmp_path / "original.cpp"
    source_path.write_bytes(b"int run;\nvoid stop;\n")
    inventory_rows: list[dict[str, JSONValue]] = []
    for ordinal, (fact, offset, column, site_id) in enumerate(
        ((fact_rows[0], 4, 5, "run"), (fact_rows[1], 14, 6, "stop"))
    ):
        inventory_rows.append(
            {
                "category": "callables",
                "ordinal": ordinal,
                "site_id": site_id,
                "fact_sha256": hashlib.sha256(
                    _canonical(fact).encode("utf-8")
                ).hexdigest(),
                "source_site": {
                    "offset": offset,
                    "line": ordinal + 1,
                    "column": column,
                    "token": "run" if ordinal == 0 else "stop",
                },
            }
        )
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                "source_fact_accounting": inventory_rows,
            }
        ),
        encoding="utf-8",
    )
    contract: dict[str, JSONValue] = {
        "source_site_inventory": {
            "path": str(inventory_path),
            "sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        },
        "normalization": {"extractor_path": "unused-in-preflighted-contract"},
        "source": {
            "path": str(source_path),
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
    }
    _validate_source_fact_accounting(contract, facts)
    original_inventory = inventory_path.read_text(encoding="utf-8")
    for mutation in ("missing", "wrong_line", "out_of_range", "duplicate_coordinate"):
        inventory = json.loads(original_inventory)
        rows = inventory["source_fact_accounting"]
        if mutation == "missing":
            rows.pop()
        elif mutation == "wrong_line":
            rows[0]["source_site"]["line"] = 2
        elif mutation == "out_of_range":
            rows[0]["source_site"]["offset"] = 999
        else:
            rows[1]["site_id"] = "run"
            rows[1]["source_site"] = {"offset": 4, "line": 1, "column": 5}
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        with pytest.raises(OracleFormatError):
            _validate_source_fact_accounting(contract, facts)


def test_authored_controls_must_cover_every_fact_category(tmp_path: Path) -> None:
    """Require source-addressed positive and negative cases per category.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the control source fixture.

    Returns
    -------
    None
    """
    control_path = tmp_path / "source-review-control.cpp"
    categories: list[str] = sorted(SOURCE_FACT_CATEGORIES)
    control_lines = [f"int case_{index};\n" for index in range(len(categories) * 2)]
    control_path.write_text("".join(control_lines), encoding="utf-8")
    cases: list[JSONValue] = []
    for category_index, category in enumerate(categories):
        for polarity_index, polarity in enumerate(("positive", "negative")):
            ordinal = category_index * 2 + polarity_index
            line_start = sum(
                len(line.encode("utf-8")) for line in control_lines[:ordinal]
            )
            token = f"case_{ordinal}".encode()
            cases.append(
                {
                    "category": category,
                    "polarity": polarity,
                    "source_site": {
                        "offset": line_start + 4,
                        "line": ordinal + 1,
                        "column": 5,
                        "token": f"case_{ordinal}",
                    },
                    "expected_fact" if polarity == "positive" else "expected_absence": {
                        "category": category,
                        "token": token.decode("utf-8"),
                    },
                }
            )
    contract: dict[str, JSONValue] = {
        "schema": "codira.clang-original-whole-file-grade/1",
        "source_authored": True,
        "oracle_method": "manual_source_review",
        "derived_from_helper_output": False,
        "source_authored_controls": [
            {
                "path": str(control_path),
                "relative_path": "source-review-control.cpp",
                "sha256": hashlib.sha256(control_path.read_bytes()).hexdigest(),
                "source_authored": True,
                "categories": cast("JSONValue", categories),
                "cases": cases,
            }
        ],
    }
    _validate_contract_header(contract)
    cases.pop()
    with pytest.raises(OracleFormatError, match="positive and negative assertions"):
        _validate_contract_header(contract)


def _include_snapshot_rows(source: bytes, mutation: str) -> list[JSONValue]:
    """Build one fixture snapshot's include rows and apply an adversarial edit.

    Parameters
    ----------
    source : bytes
        Exact source bytes for the test contract.
    mutation : str
        ``valid``, ``missing``, ``extra``, or ``duplicate`` row treatment.

    Returns
    -------
    list[JSONValue]
        Snapshot rows after the selected mutation.
    """
    parsed = _source_literal_includes(source)
    assert parsed is not None
    rows: list[JSONValue] = cast("list[JSONValue]", parsed)
    if mutation == "missing":
        rows.pop()
    elif mutation == "extra":
        rows.append({"kind": "include_system", "name": "extra.h", "line": 1})
    elif mutation == "duplicate":
        rows.append(dict(cast("dict[str, JSONValue]", rows[0])))
    elif mutation == "wrong_same_count":
        cast("dict[str, JSONValue]", rows[0])["name"] = "wrong.h"
    else:
        assert mutation == "valid"
    return rows


def _run_grade_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    held_category: str | None = None,
    diverge_backend: bool = False,
    inject_negative_control: bool = False,
    include_source: bytes = b"",
    include_mutation: str | None = None,
    include_state: str | None = None,
) -> dict[str, JSONValue]:
    """Run grade_contract with only external database/profile readers stubbed."""
    source = tmp_path / "fixture.cpp"
    source.write_bytes(include_source + b"int value;\n")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    fixture_root = tmp_path / "fixtures"
    fixture_root.mkdir()
    (fixture_root / "fixture.cpp").write_bytes(source.read_bytes())
    oracle_case: dict[str, JSONValue] = {"language": "cpp"}
    for category in FACT_CATEGORIES:
        oracle_case[category] = []
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(
        json.dumps(
            {
                "oracle_version": 1,
                "source_authored_oracle": True,
                "cases": {"fixture.cpp": oracle_case},
                "header_context_requests": [],
                "identity_invariants": [],
                "identity_observation_requests": [],
            }
        ),
        encoding="utf-8",
    )
    inventory_path = tmp_path / "source-site-inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "source_sha256": source_hash,
                "source_fact_accounting": [],
            }
        ),
        encoding="utf-8",
    )
    profile = tmp_path / "profiles.json"
    profile.write_text("{}", encoding="utf-8")
    control_path = tmp_path / "source-review-controls.cpp"
    category_names = sorted(SOURCE_FACT_CATEGORIES)
    control_lines = ["#define DECL_ALIAS(N) asm(#N)\n"]
    control_case_descriptors: list[tuple[str, str, int]] = []
    for category_index, category in enumerate(category_names):
        for polarity_index, polarity in enumerate(("positive", "negative")):
            ordinal = category_index * 2 + polarity_index
            line = (
                "void impl_actual_alias() DECL_ALIAS(actual_alias);\n"
                if category == "generated_declarations" and polarity == "positive"
                else "int case_target(); int case_caller(){ return case_target(); }\n"
                if category == "calls" and polarity == "positive"
                else f"int case_{ordinal};\n"
            )
            control_lines.append(line)
            control_case_descriptors.append((category, polarity, ordinal))
    control_path.write_text("".join(control_lines), encoding="utf-8")
    (fixture_root / "source-review-controls.cpp").write_bytes(control_path.read_bytes())
    control_cases: list[JSONValue] = []
    control_oracle_case: dict[str, JSONValue] = {"language": "cpp"}
    for category in FACT_CATEGORIES:
        control_oracle_case[category] = []
    for category, polarity, ordinal in control_case_descriptors:
        line_start = sum(
            len(line.encode("utf-8")) for line in control_lines[: ordinal + 1]
        )
        line_number = ordinal + 2
        token = (
            "case_target"
            if category == "calls" and polarity == "positive"
            else f"case_{ordinal}"
        )
        generated = category == "generated_declarations" and polarity == "positive"
        if generated:
            token = "DECL_ALIAS"
        line_text = control_lines[ordinal + 1]
        token_index = (
            line_text.rindex(token)
            if category == "calls" and polarity == "positive"
            else line_text.index(token)
        )
        site_offset = line_start + token_index
        expected_fact: dict[str, JSONValue] = (
            {
                "category": category,
                "line": line_number,
                "name": "impl_actual_alias",
                "role": "prototype",
                "linkage_name": "actual_alias",
                "source_evidence": {
                    "macro": "DECL_ALIAS",
                    "invocation_line": line_number,
                    "macro_definition_line": 1,
                    "argument": "actual_alias",
                    "macro_expression": "asm(#N)",
                    "invocation_span": list(
                        _source_macro_invocation_span(
                            control_path, "DECL_ALIAS", line_number
                        )
                    ),
                },
            }
            if generated
            else (
                {
                    "category": category,
                    "line": line_number,
                    "caller": "case_caller",
                    "target": "case_target",
                    "resolution": "resolved",
                }
                if category == "calls" and polarity == "positive"
                else {"category": category, "line": line_number, "name": token}
            )
        )
        control_cases.append(
            {
                "category": category,
                "polarity": polarity,
                "source_site": {
                    "offset": site_offset,
                    "line": line_number,
                    "column": site_offset - line_start + 1,
                    "token": token,
                },
                "expected_fact"
                if polarity == "positive"
                else "expected_absence": expected_fact
                if polarity == "positive"
                else {"category": category, "name": f"absent_{ordinal}"},
            }
        )
        if polarity == "positive":
            cast("list[JSONValue]", control_oracle_case[category]).append(expected_fact)
    oracle_path.write_text(
        json.dumps(
            {
                "oracle_version": 1,
                "source_authored_oracle": True,
                "cases": {
                    "fixture.cpp": oracle_case,
                    "source-review-controls.cpp": control_oracle_case,
                },
                "header_context_requests": [],
                "identity_invariants": [],
                "identity_observation_requests": [],
            }
        ),
        encoding="utf-8",
    )
    contract: dict[str, JSONValue] = {
        "schema": "codira.clang-original-whole-file-grade/1",
        "source_authored": True,
        "oracle_method": "manual_source_review",
        "derived_from_helper_output": False,
        "source_authored_controls": [
            {
                "path": str(control_path),
                "relative_path": "source-review-controls.cpp",
                "sha256": hashlib.sha256(control_path.read_bytes()).hexdigest(),
                "source_authored": True,
                "categories": cast("JSONValue", category_names),
                "cases": control_cases,
            }
        ],
        "source": {
            "relative_path": "fixture.cpp",
            "path": str(source),
            "sha256": source_hash,
        },
        "source_site_inventory": {
            "path": str(inventory_path),
            "sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        },
        "categories": {
            category: {
                "state": (
                    "held"
                    if category == held_category
                    else include_state
                    if category == "includes" and include_state is not None
                    else "graded"
                ),
                "independent_basis": "source-bound empty inventory for test fixture",
                "inventory_complete": True,
                "reason": "test holds this category"
                if category == held_category
                else "",
            }
            for category in FACT_CATEGORIES
        },
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    receipts = {
        name: tmp_path / f"{name}.receipt.json" for name in ("sqlite", "duckdb")
    }
    for path in receipts.values():
        path.write_text("{}", encoding="utf-8")
    snapshots: dict[str, Path] = {}
    database_bindings = {
        name: _generation_binding(name) for name in ("sqlite", "duckdb")
    }
    for backend in ("sqlite", "duckdb"):
        rows: dict[str, JSONValue] = {
            "source_sha256": source_hash,
            "analysis_input_fingerprint": f"{backend}-context",
        }
        rows.update({category: [] for category in FACT_CATEGORIES})
        if include_mutation is not None:
            rows["includes"] = cast(
                "JSONValue",
                _include_snapshot_rows(source.read_bytes(), include_mutation),
            )
        if backend == "duckdb" and diverge_backend:
            rows["calls"] = [{"name": "unexpected"}]
        control_snapshot_rows: dict[str, JSONValue] = {
            category: (
                [
                    {
                        **cast("dict[str, JSONValue]", fact),
                        "resolved": True,
                        "callee_stable_id": "callee-stable-id",
                        "caller_stable_id": "caller-stable-id",
                        "resolution_mode": "exact",
                        "target_identity_namespace": "usr",
                        "target_identity_value": "callee-usr",
                        "caller_qualified_name": "case_caller",
                        "callee_qualified_name": "case_target",
                    }
                    if category == "calls"
                    else cast("dict[str, JSONValue]", fact)
                    for fact in cast("list[JSONValue]", control_oracle_case[category])
                ]
                if category == "calls"
                else control_oracle_case[category]
            )
            for category in FACT_CATEGORIES
        }
        if inject_negative_control:
            negative_declaration = next(
                ordinal
                for category, polarity, ordinal in control_case_descriptors
                if category == "declarations" and polarity == "negative"
            )
            cast("list[JSONValue]", control_snapshot_rows["declarations"]).append(
                {
                    "category": "declarations",
                    "name": f"absent_{negative_declaration}",
                }
            )
        snapshot: dict[str, JSONValue] = {
            "snapshot_version": 1,
            "backend": backend,
            "cases": {
                "fixture.cpp": rows,
                "source-review-controls.cpp": {
                    "source_sha256": hashlib.sha256(
                        control_path.read_bytes()
                    ).hexdigest(),
                    "analysis_input_fingerprint": f"{backend}-control-context",
                    **control_snapshot_rows,
                },
            },
            "database_binding": database_bindings[backend],
            "profile_document_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        }
        snapshots[backend] = tmp_path / f"{backend}.snapshot.json"
        snapshots[backend].write_text(json.dumps(snapshot), encoding="utf-8")

    bindings: dict[str, JSONValue] = {
        "profile_collection_path": str(profile),
        "profile_collection_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        "analysis_context_identity": "frontend-context",
        "analyzer_version": "49",
    }
    monkeypatch.setattr(
        "scripts.clang_original_whole_file_grade._validate_context_bindings",
        lambda _contract: bindings,
    )
    monkeypatch.setattr(
        "scripts.clang_original_whole_file_grade._validate_analysis_receipt",
        lambda request: {
            "native_stdout_sha256": "stdout",
            "native_stderr_sha256": "stderr",
        },
    )
    monkeypatch.setattr(
        "scripts.clang_original_whole_file_grade._validate_cross_backend_receipts",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "scripts.clang_original_whole_file_grade._validate_indexed_context_identity",
        lambda *_args: {"frontend": "frontend-context"},
    )
    return grade_contract(
        GradeRequest(
            contract_path,
            oracle_path,
            fixture_root,
            snapshots,
            receipts,
            database_bindings,
            profile,
        )
    )


def test_manual_source_review_assertions_cannot_admit_full_flow(tmp_path: Path) -> None:
    """Keep source categories held despite matching human-authored controls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the full-contract fixture.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(tmp_path, monkeypatch)
    assert report["source_authored_control_failures"] == {"sqlite": [], "duckdb": []}
    assert report["passed"] is False
    assert report["scope_complete"] is False
    held_categories = cast(
        "list[str]", report["categories_held_without_machine_semantics"]
    )
    assert set(held_categories) == set(FACT_CATEGORIES) - {"coverage", "includes"}
    assert report["held_category_count"] == len(held_categories)


def test_literal_include_evaluator_is_bounded_and_exact() -> None:
    """Derive direct include rows and hold unsupported preprocessing syntax.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    assert _source_literal_includes(
        b'/* prefix */\n#include <alpha/beta.h>\n#include "local.h"\n'
    ) == [
        {"kind": "include_system", "name": "alpha/beta.h", "line": 2},
        {"kind": "include_local", "name": "local.h", "line": 3},
    ]
    for unsupported in (
        b"#if FEATURE\n#include <alpha.h>\n#endif\n",
        b"#include HEADER_NAME\n",
        b"#include <alpha.h> \\\n\n",
        b"??=include <alpha.h>\n",
        b"%:if FEATURE\n#include <alpha.h>\n%:endif\n",
        b"\xef\xbb\xbf#if FEATURE\n#include <alpha.h>\n#endif\n",
        b"%:include <alpha.h>\n",
        b'const char *text = R"(\n#include <false.h>\n)";\n',
        b"/* unterminated comment\n#include <alpha.h>\n",
    ):
        assert _source_literal_includes(unsupported) is None


@pytest.mark.parametrize(
    "source",
    [
        b"%:if FEATURE\n#include <alpha.h>\n%:endif\n",
        b"\xef\xbb\xbf#if FEATURE\n#include <alpha.h>\n#endif\n",
    ],
)
def test_unsupported_include_preprocessor_forms_remain_held(
    source: bytes, tmp_path: Path
) -> None:
    """Keep includes held when alternate directive spellings are present.

    Parameters
    ----------
    source : bytes
        Unsupported source text to bind to the fixture.
    tmp_path : pathlib.Path
        Temporary workspace for the full-contract fixture.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(tmp_path, monkeypatch, include_source=source)
    held_categories = cast(
        "list[str]", report["categories_held_without_machine_semantics"]
    )
    assert "includes" in held_categories
    includes = cast(
        "dict[str, JSONValue]",
        cast("dict[str, JSONValue]", report["category_reports"])["includes"],
    )
    assert includes["semantic_validation"] == (
        "held: no independent machine evaluator is implemented"
    )


def test_literal_includes_are_machine_graded_from_source_bytes(tmp_path: Path) -> None:
    """Use exact source directives as the include oracle in full flow.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the full-contract fixture.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(
            tmp_path,
            monkeypatch,
            include_source=b'#include <alpha.h>\n#include "local.h"\n',
            include_mutation="valid",
        )
    includes = cast(
        "dict[str, JSONValue]",
        cast("dict[str, JSONValue]", report["category_reports"])["includes"],
    )
    assert includes["expected_count"] == 2
    assert includes["semantic_validation"] == (
        "source-derived exhaustive literal directive inventory"
    )
    assert includes["grader_failures"] == []
    assert report["passed"] is False
    assert "calls" in cast(
        "list[str]", report["categories_held_without_machine_semantics"]
    )


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate"])
def test_literal_include_evaluator_rejects_snapshot_drift(
    mutation: str, tmp_path: Path
) -> None:
    """Reject missing, extra, and duplicate persisted include rows.

    Parameters
    ----------
    mutation : str
        Snapshot mutation to exercise.
    tmp_path : pathlib.Path
        Temporary workspace for the full-contract fixture.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(
            tmp_path,
            monkeypatch,
            include_source=b"#include <alpha.h>\n",
            include_mutation=mutation,
        )
    includes = cast(
        "dict[str, JSONValue]",
        cast("dict[str, JSONValue]", report["category_reports"])["includes"],
    )
    assert includes["grader_failures"]
    assert includes["exact_count_by_backend"] == {"sqlite": False, "duckdb": False}
    assert report["passed"] is False


def test_nonempty_include_inventory_rejects_not_applicable_state(
    tmp_path: Path,
) -> None:
    """Count same-sized wrong rows despite an invalid not-applicable claim.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the full-contract fixture.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(
            tmp_path,
            monkeypatch,
            include_source=b"#include <alpha.h>\n",
            include_mutation="wrong_same_count",
            include_state="not_applicable",
        )
    includes = cast(
        "dict[str, JSONValue]",
        cast("dict[str, JSONValue]", report["category_reports"])["includes"],
    )
    assert includes["state"] == "not_applicable"
    assert includes["expected_count"] == 1
    assert includes["observed_counts"] == {"sqlite": 1, "duckdb": 1}
    assert includes["exact_count_by_backend"] == {"sqlite": True, "duckdb": True}
    assert includes["backend_parity"] is True
    failures = cast("list[dict[str, JSONValue]]", includes["grader_failures"])
    assert any(
        failure.get("reason")
        == "persisted include rows differ from the exhaustive source-derived literal directive inventory"
        for failure in failures
    )
    assert any(
        failure.get("reason")
        == "nonempty source-derived include inventory cannot be not_applicable"
        for failure in failures
    )
    assert report["mismatched_category_count"] == 1
    assert report["passed"] is False


@pytest.mark.parametrize(
    "mutation",
    ["held_category", "backend_divergence", "negative_control_emission"],
)
def test_grade_contract_adversarial_full_flow(mutation: str, tmp_path: Path) -> None:
    """Keep held categories, parity gaps, and forbidden rows from passing.

    Parameters
    ----------
    mutation : str
        Adversarial full-contract mutation to apply.
    tmp_path : pathlib.Path
        Temporary workspace for the contract and snapshots.

    Returns
    -------
    None
    """
    with pytest.MonkeyPatch.context() as monkeypatch:
        report = _run_grade_flow(
            tmp_path,
            monkeypatch,
            held_category="calls" if mutation == "held_category" else None,
            diverge_backend=mutation == "backend_divergence",
            inject_negative_control=mutation == "negative_control_emission",
        )
    assert report["passed"] is False
    assert report["scope_complete"] is False
    if mutation == "negative_control_emission":
        failures = cast(
            "dict[str, list[dict[str, JSONValue]]]",
            report["source_authored_control_failures"],
        )
        for backend in ("sqlite", "duckdb"):
            assert any(
                failure.get("reason")
                == "persisted row violates a source-authored negative control"
                for failure in failures[backend]
            )


def test_database_persisted_analysis_status_overrides_receipt_claims(
    tmp_path: Path,
) -> None:
    """Reject receipt status claims that differ from the SQLite status row.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the SQLite index fixture.

    Returns
    -------
    None
    """
    database = tmp_path / "index.sqlite"
    source = (tmp_path / "source.cpp").resolve()
    source_hash = "source-hash"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE files(path TEXT, hash TEXT, analyzer_name TEXT, analyzer_version TEXT);"
        "CREATE TABLE analysis_status(path TEXT, grammar TEXT, target_contract TEXT, diagnostics TEXT, "
        "reliable_categories TEXT, omitted_categories TEXT, coverage_state TEXT);"
    )
    connection.execute(
        "INSERT INTO files VALUES (?, ?, ?, ?)", (str(source), source_hash, "cpp", "49")
    )
    connection.execute(
        "INSERT INTO analysis_status VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            str(source),
            "clang-cpp-frontend",
            "{}",
            "[]",
            '["callable"]',
            "[]",
            "complete",
        ),
    )
    connection.commit()
    connection.close()
    persisted = _read_actual_analysis_status(database, "sqlite", source, source_hash)
    receipt: dict[str, JSONValue] = {
        "source_sha256": source_hash,
        "coverage_state": "complete",
        "omitted_categories": [],
        "grammar": "clang-cpp-frontend",
        "reliable_categories": ["callable"],
    }
    _validate_persisted_status_claims(receipt, persisted, "sqlite")
    receipt["omitted_categories"] = ["declaration"]
    with pytest.raises(
        OracleFormatError, match="differs from the persisted database row"
    ):
        _validate_persisted_status_claims(receipt, persisted, "sqlite")


def test_persisted_status_must_prove_clang_cpp_frontend(tmp_path: Path) -> None:
    """Reject a source row whose persisted target uses Tree-sitter.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace for the build-receipt fixture.

    Returns
    -------
    None
    """
    source = (tmp_path / "source.cpp").resolve()
    build_receipt = tmp_path / "build-receipt.json"
    build_receipt.write_text(
        json.dumps(
            {
                "compiler_sha256": "compiler-sha",
                "resource_dir": "/clang/resource",
                "resource_probe_sha256": "resource-sha",
            }
        ),
        encoding="utf-8",
    )
    bindings: dict[str, JSONValue] = {
        "compiler_identity": "/clang/bin/clang++",
        "compiler_version": "clang 22",
        "helper_path": "/helper/clang-frontend",
        "helper_sha256": "helper-sha",
        "build_receipt_path": str(build_receipt),
        "build_receipt_sha256": "receipt-sha",
        "profile_identity": "profile-sha",
    }
    persisted: dict[str, JSONValue] = {
        "grammar": "clang-cpp-frontend",
        "target_contract": {
            "language": "cpp",
            "frontend": "clang",
            "requested_source_path": str(source),
            "requested_source_sha256": "source-sha",
            "profile_identity": "profile-sha",
            "toolchain_identity": {
                "compiler_path": "/clang/bin/clang++",
                "compiler_version": "clang 22",
                "compiler_sha256": "compiler-sha",
                "resource_dir": "/clang/resource",
                "resource_probe_sha256": "resource-sha",
                "helper_path": "/helper/clang-frontend",
                "helper_sha256": "helper-sha",
                "build_receipt_sha256": "receipt-sha",
            },
        },
    }
    _validate_persisted_clang_identity(
        persisted, bindings, source, "source-sha", "sqlite"
    )
    target = cast("dict[str, JSONValue]", persisted["target_contract"])
    target["frontend"] = "tree-sitter"
    with pytest.raises(OracleFormatError, match=r"not the Clang C\+\+ frontend"):
        _validate_persisted_clang_identity(
            persisted, bindings, source, "source-sha", "sqlite"
        )


def _source_owned_ast_fixture() -> tuple[
    bytes,
    Path,
    dict[str, JSONValue],
    dict[str, object],
    dict[str, JSONValue],
    dict[str, dict[str, JSONValue]],
    Path,
    Path,
]:
    """Build a small source-bound record, field and function AST case.

    Parameters
    ----------
    None

    Returns
    -------
    tuple
        Source bytes and path, freshly normalized facts, raw AST, analyzer
        capabilities, backend rows, normalizer copy and working directory.
    """
    source = b"struct R { int x; };\nint f(struct R *r) { int local; return 0; }\n"
    source_path = Path("/fixture.c")
    working_directory = Path.cwd()
    record_offset = source.index(b"R")
    field_offset = source.index(b"x")
    function_offset = source.index(b"f(")
    variable_offset = source.index(b"local")
    raw_ast: dict[str, object] = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "kind": "RecordDecl",
                "name": "R",
                "tagUsed": "struct",
                "completeDefinition": True,
                "loc": {
                    "file": str(source_path),
                    "line": 1,
                    "col": record_offset + 1,
                    "offset": record_offset,
                    "tokLen": 1,
                },
                "inner": [
                    {
                        "kind": "FieldDecl",
                        "name": "x",
                        "type": {"qualType": "int"},
                        "loc": {
                            "file": str(source_path),
                            "line": 1,
                            "col": field_offset + 1,
                            "offset": field_offset,
                            "tokLen": 1,
                        },
                    }
                ],
            },
            {
                "kind": "FunctionDecl",
                "name": "f",
                "type": {"qualType": "int (struct R *)"},
                "loc": {
                    "file": str(source_path),
                    "line": 2,
                    "col": function_offset - source.rfind(b"\n", 0, function_offset),
                    "offset": function_offset,
                    "tokLen": 1,
                },
                "inner": [
                    {
                        "kind": "CompoundStmt",
                        "inner": [
                            {
                                "kind": "VarDecl",
                                "name": "local",
                                "type": {"qualType": "int"},
                                "loc": {
                                    "file": str(source_path),
                                    "line": 2,
                                    "col": variable_offset
                                    - source.rfind(b"\n", 0, variable_offset),
                                    "offset": variable_offset,
                                    "tokLen": 5,
                                },
                            }
                        ],
                    }
                ],
            },
        ],
    }
    normalized = cast(
        "dict[str, JSONValue]",
        normalize_ast(raw_ast, source_path, source, working_directory),
    )
    capabilities: dict[str, JSONValue] = {
        "analyzer_version": "30",
        "supports": ["callable", "type", "variable"],
        "does_not_support": ["namespace"],
    }
    category_rows: dict[str, JSONValue] = {
        "declarations": [{"kind": "struct", "line": 1, "name": "R"}],
        "fields": [{"line": 1, "name": "x", "owner": "R", "type": "int"}],
        "callables": [
            {
                "definition_line": 2,
                "kind": "function",
                "name": "f",
                "parameter_types": ["struct R *"],
                "return_type": "int",
            }
        ],
    }
    return (
        source,
        source_path,
        normalized,
        raw_ast,
        capabilities,
        {"sqlite": dict(category_rows), "duckdb": dict(category_rows)},
        Path("scripts/clang_reference_facts.py").resolve(),
        working_directory,
    )


def _source_owned_wrapper_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SourceOwnedAstGradeRequest, dict[str, Path]]:
    """Build a bound miniature capture and patch only external analyzers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary evidence workspace.
    monkeypatch : pytest.MonkeyPatch
        Fixture for deterministic profile and database readers.

    Returns
    -------
    tuple
        Complete wrapper request and named mutable evidence paths.
    """

    def write_json(path: Path, value: object) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    repo = tmp_path / "source-repository"
    source_path = repo / "src" / "unit.c"
    source_path.parent.mkdir(parents=True)
    source, _fixture_path, _facts, raw_ast, _caps, rows, _normalizer, _cwd = (
        _source_owned_ast_fixture()
    )
    source_path.write_bytes(source)

    def rewrite_ast(value: object) -> None:
        if isinstance(value, dict):
            location = value.get("loc")
            if isinstance(location, dict) and "file" in location:
                location["file"] = str(source_path)
            for child in value.values():
                rewrite_ast(child)
        elif isinstance(value, list):
            for child in value:
                rewrite_ast(child)

    rewrite_ast(raw_ast)
    normalized = cast(
        "dict[str, JSONValue]",
        normalize_ast(raw_ast, source_path, source, repo),
    )
    evidence = tmp_path / "evidence"
    raw_path = evidence / "raw-ast.json"
    raw_hash = write_json(raw_path, raw_ast)
    normalized_path = evidence / "normalized.json"
    normalized_hash = write_json(normalized_path, normalized)
    normalizer_path = Path("scripts/clang_reference_facts.py").resolve()
    normalizer_hash = hashlib.sha256(normalizer_path.read_bytes()).hexdigest()

    profile_path = evidence / "selected-profile.json"
    profile_hash = write_json(profile_path, {"profile": "fixture"})
    compile_database_path = evidence / "compile_commands.json"
    compile_database_hash = write_json(compile_database_path, [])
    compiler_path = evidence / "clang"
    compiler_path.write_bytes(b"compiler fixture")
    compiler_hash = hashlib.sha256(compiler_path.read_bytes()).hexdigest()
    helper_path = evidence / "helper.py"
    helper_path.write_bytes(b"helper fixture")
    helper_hash = hashlib.sha256(helper_path.read_bytes()).hexdigest()
    build_receipt_path = evidence / "build-receipt.json"
    build_receipt = {"resource_dir": "/resource", "resource_probe_sha256": "probe"}
    build_receipt_hash = write_json(build_receipt_path, build_receipt)
    context_identity = json.dumps(
        {"clang_frontend_fingerprint": "fixture-frontend"}, sort_keys=True
    )
    profile = SimpleNamespace(
        working_directory=str(repo),
        argv=["profile-clang", "-c", str(source_path)],
        include_directories=(),
        dependencies=(),
        identity="fixture-profile-identity",
    )
    monkeypatch.setattr(
        grader,
        "_load_bound_frontend_profile",
        lambda *_args: ("fixture-frontend", profile),
    )
    monkeypatch.setattr(grader, "_validate_compile_database_row", lambda *_args: None)
    monkeypatch.setattr(
        codira_clang_frontend,
        "frontend_profile_fingerprint",
        lambda *_args: "fixture-frontend",
    )
    monkeypatch.setattr(
        codira_clang_frontend, "directory_membership_sha256", lambda _path: "unused"
    )

    class FixtureAnalyzer:
        """Provide the persisted C analyzer capability declaration."""

        def configure(self, _configuration: dict[str, str]) -> None:
            """Accept the validated captured profile configuration."""

        def analyzer_capability_declaration(self) -> SimpleNamespace:
            """Return the analyzer identity stored in the fixture databases."""
            return SimpleNamespace(
                analyzer_version="30",
                supports=("callable", "type", "variable"),
                does_not_support=("namespace",),
            )

    monkeypatch.setattr(codira_analyzer_c, "build_analyzer", lambda: FixtureAnalyzer())
    monkeypatch.setattr(
        inspect,
        "getsourcefile",
        lambda _package: str(Path(codira_analyzer_c.__file__).resolve()),
    )

    guard_profile: dict[str, JSONValue] = {
        "dependencies": [],
        "include_directories": [],
    }
    guard_value = {
        "source": {
            "repository": str(repo),
            "sha256": hashlib.sha256(source).hexdigest(),
        },
        "profile": guard_profile,
    }
    before_path = evidence / "guards-before.json"
    before_hash = write_json(before_path, guard_value)
    after_path = evidence / "guards-after.json"
    after_hash = write_json(after_path, guard_value)
    prepared_path = evidence / "prepared-inputs.json"
    prepared_value = {
        "identity": "fixture-capture",
        "profile_sha256": profile_hash,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "working_directory": str(repo),
        "expected_input_hashes": {
            "source": hashlib.sha256(source).hexdigest(),
            "profile": profile_hash,
            "compile_database": compile_database_hash,
            "compiler": compiler_hash,
            "helper": helper_hash,
            "build_receipt": build_receipt_hash,
        },
        "compiler_path": str(compiler_path),
        "compiler_sha256": compiler_hash,
        "helper_path": str(helper_path),
        "helper_sha256": helper_hash,
        "build_receipt_path": str(build_receipt_path),
        "build_receipt_sha256": build_receipt_hash,
        "compiler_argv": [
            str(compiler_path),
            str(source_path),
            "-Xclang",
            "-ast-dump=json",
            "-fsyntax-only",
        ],
    }
    prepared_hash = write_json(prepared_path, prepared_value)
    invocation_path = evidence / "invocation.json"
    invocation_value = {
        "identity": "fixture-capture",
        "working_directory": str(repo),
        "compiler_argv": prepared_value["compiler_argv"],
    }
    invocation_hash = write_json(invocation_path, invocation_value)
    terminal_path = evidence / "terminal.json"
    terminal_value = {
        "identity": "fixture-capture",
        "status": "complete",
        "return_code": 0,
        "admission": False,
        "whole_file_grade": False,
        "stdout_sha256": raw_hash,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "profile_sha256": profile_hash,
        "compiler_sha256": compiler_hash,
    }
    terminal_hash = write_json(terminal_path, terminal_value)
    summary_path = evidence / "capture-summary.json"
    summary_value = {
        "identity": "fixture-capture",
        "status": "complete",
        "llvm_source_repository": {"pre_post_guards_equal": True},
        "source": {
            "path": str(source_path),
            "sha256": hashlib.sha256(source).hexdigest(),
        },
        "profile": {
            "path": str(profile_path),
            "sha256": profile_hash,
            "include_directory_count": 0,
        },
        "compile_database": {
            "path": str(compile_database_path),
            "sha256": compile_database_hash,
        },
        "toolchain": {
            "compiler_path": str(compiler_path),
            "compiler_sha256": compiler_hash,
            "compiler_version": "fixture-clang",
            "helper_path": str(helper_path),
            "helper_sha256": helper_hash,
        },
        "attempt": {
            "prepared_inputs_sha256": prepared_hash,
            "stdout_sha256": raw_hash,
            "return_code": 0,
            "guards_before_sha256": before_hash,
            "guards_after_sha256": after_hash,
            "invocation_path": str(invocation_path),
            "invocation_sha256": invocation_hash,
        },
    }
    summary_hash = write_json(summary_path, summary_value)

    snapshot_paths: dict[str, Path] = {}
    binding_paths: dict[str, Path] = {}
    status_paths: dict[str, Path] = {}
    status_by_database: dict[str, dict[str, JSONValue]] = {}
    context_by_database: dict[str, str] = {}
    key = "src/unit.c"
    source_hash = hashlib.sha256(source).hexdigest()
    target_contract = {
        "language": "c",
        "frontend": "clang",
        "requested_source_path": str(source_path),
        "requested_source_sha256": source_hash,
        "profile_identity": profile.identity,
        "dependency_closure": {"file_count": 0, "status": "complete"},
        "toolchain_identity": {
            "compiler_version": "fixture-clang",
            "compiler_path": str(compiler_path),
            "compiler_sha256": compiler_hash,
            "helper_path": str(helper_path),
            "helper_sha256": helper_hash,
            "build_receipt_sha256": build_receipt_hash,
            "resource_dir": build_receipt["resource_dir"],
            "resource_probe_sha256": build_receipt["resource_probe_sha256"],
        },
    }
    persisted_status: dict[str, JSONValue] = {
        "source_sha256": source_hash,
        "analyzer_name": "c",
        "analyzer_version": "30",
        "grammar": "clang-c-frontend",
        "target_contract": cast("JSONValue", target_contract),
        "reliable_categories": ["function", "declaration"],
        "omitted_categories": [],
        "coverage_state": "complete",
    }
    for backend in ("sqlite", "duckdb"):
        backend_root = evidence / backend
        database_path = backend_root / (
            "index.db" if backend == "sqlite" else "index.duckdb"
        )
        database_path.parent.mkdir(parents=True)
        database_path.write_bytes(f"{backend} database".encode())
        write_json(
            backend_root / "metadata.json",
            {"backend_name": backend, "schema_version": "29"},
        )
        write_json(
            backend_root / "index-generation.json",
            {
                "backend_name": backend,
                "analysis_fingerprint": f"{backend}-analysis",
                "generation": 1,
                "analyzer_inventory": [],
                "git_commit": "fixture-commit",
            },
        )
        binding = _database_generation_binding(database_path, backend)
        binding_path = evidence / f"{backend}-binding.json"
        write_json(binding_path, binding)
        binding_paths[backend] = binding_path
        snapshot = {
            "snapshot_version": 1,
            "backend": backend,
            "database_binding": binding,
            "profile_document_sha256": profile_hash,
            "cases": {
                key: {
                    "source_sha256": source_hash,
                    "analysis_input_fingerprint": context_identity,
                    "declarations": rows[backend]["declarations"],
                    "fields": rows[backend]["fields"],
                    "callables": rows[backend]["callables"],
                }
            },
        }
        snapshot_path = evidence / f"{backend}-snapshot.json"
        write_json(snapshot_path, snapshot)
        snapshot_paths[backend] = snapshot_path
        status_path = evidence / f"{backend}-status.json"
        write_json(
            status_path,
            {**persisted_status, "analysis_input_fingerprint": context_identity},
        )
        status_paths[backend] = status_path
        status_by_database[str(database_path.resolve())] = persisted_status
        context_by_database[str(database_path.resolve())] = context_identity

    monkeypatch.setattr(
        grader,
        "_read_indexed_context_identity",
        lambda _backend, database, *_args: context_by_database[str(database.resolve())],
    )
    monkeypatch.setattr(
        grader,
        "_read_actual_analysis_status",
        lambda database, *_args: status_by_database[str(database.resolve())],
    )
    request = SourceOwnedAstGradeRequest(
        source_path=source_path,
        source_key=key,
        normalized_path=normalized_path,
        normalization_record_path=evidence / "normalization-record.json",
        capture_summary_path=summary_path,
        prepared_inputs_path=prepared_path,
        guards_before_path=before_path,
        guards_after_path=after_path,
        snapshot_paths=snapshot_paths,
        database_binding_paths=binding_paths,
        status_paths=status_paths,
        profile_document_path=profile_path,
        repository_root=Path.cwd(),
    )
    record = {
        "schema": "codira.clang-cfp017-native-cli-ast-normalization/1",
        "status": "complete",
        "whole_file_admission": False,
        "normalized_output_path": str(normalized_path.resolve()),
        "normalized_output_sha256": normalized_hash,
        "normalized_reference_path": str(normalized_path.resolve()),
        "normalized_reference_sha256": normalized_hash,
        "source_path": str(source_path.resolve()),
        "source_sha256": source_hash,
        "normalizer_path": str(normalizer_path),
        "normalizer_sha256": normalizer_hash,
        "raw_ast_path": str(raw_path),
        "raw_ast_sha256": raw_hash,
        "capture_input_binding_path": str(summary_path.resolve()),
        "capture_input_binding_sha256": summary_hash,
        "capture_identity": "fixture-capture",
        "capture_terminal_path": str(terminal_path.resolve()),
        "capture_terminal_sha256": terminal_hash,
        "capture_prepared_inputs_sha256": prepared_hash,
        "profile_sha256": profile_hash,
        "working_directory": str(repo),
    }
    write_json(request.normalization_record_path, record)
    paths = {
        "source": source_path,
        "normalization": normalized_path,
        "profile": profile_path,
        "guard": after_path,
        "status": status_paths["sqlite"],
        "snapshot": snapshot_paths["sqlite"],
        "database": evidence / "sqlite" / "index.db",
        "capture": terminal_path,
        "record": request.normalization_record_path,
    }
    return request, paths


def test_source_owned_ast_categories_reconcile_exact_facts() -> None:
    """Grade only exact source-owned records, fields and functions.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source, source_path, normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    assert normalized["source_path"] == str(source_path)
    report = grade_source_owned_ast_categories(
        normalized, raw_ast, source, capabilities, rows, normalizer, cwd
    )
    assert report["whole_file_admission"] is False
    assert report["scope_complete"] is False
    categories = cast("dict[str, JSONValue]", report["categories"])
    assert set(categories) == {"declarations", "fields", "callables"}
    assert all(
        cast("dict[str, JSONValue]", item)["state"] == "graded"
        for item in categories.values()
    )


def test_source_owned_evidence_wrapper_accepts_bound_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise a complete positive pass through the evidence wrapper.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary evidence workspace.
    monkeypatch : pytest.MonkeyPatch
        Fixture for the deterministic profile and database readers.

    Returns
    -------
    None
    """
    request, _paths = _source_owned_wrapper_fixture(tmp_path, monkeypatch)

    report = grade_source_owned_ast_evidence(request)

    assert report["scope_complete"] is False
    assert report["whole_file_admission"] is False
    categories = cast("dict[str, JSONValue]", report["categories"])
    assert all(
        cast("dict[str, JSONValue]", categories[name])["state"] == "graded"
        for name in ("declarations", "fields", "callables")
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "source",
        "normalization",
        "profile",
        "guard",
        "status",
        "snapshot",
        "database",
        "capture",
    ],
)
def test_source_owned_evidence_wrapper_holds_mutated_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    """Reject stale retained inputs and hold semantically wrong snapshots.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary evidence workspace.
    monkeypatch : pytest.MonkeyPatch
        Fixture for deterministic profile and database readers.
    mutation : str
        Evidence identity changed after fixture construction.

    Returns
    -------
    None
    """
    request, paths = _source_owned_wrapper_fixture(tmp_path, monkeypatch)
    target = paths[mutation]
    if mutation == "snapshot":
        snapshot = json.loads(target.read_text(encoding="utf-8"))
        snapshot["cases"][request.source_key]["fields"] = []
        target.write_text(json.dumps(snapshot), encoding="utf-8")
        report = grade_source_owned_ast_evidence(request)
        categories = cast("dict[str, JSONValue]", report["categories"])
        assert cast("dict[str, JSONValue]", categories["fields"])["state"] == "held"
        assert report["whole_file_admission"] is False
        return
    if mutation == "source":
        target.write_bytes(target.read_bytes() + b"\n")
    elif mutation == "normalization":
        target.write_bytes(target.read_bytes() + b" ")
    elif mutation == "profile":
        target.write_text('{"profile":"changed"}', encoding="utf-8")
    elif mutation == "guard":
        target.write_text("{}", encoding="utf-8")
    elif mutation == "status":
        status = json.loads(target.read_text(encoding="utf-8"))
        status["coverage_state"] = "incomplete"
        target.write_text(json.dumps(status), encoding="utf-8")
    elif mutation == "database":
        target.write_bytes(target.read_bytes() + b" changed")
    elif mutation == "capture":
        terminal = json.loads(target.read_text(encoding="utf-8"))
        terminal["return_code"] = 1
        target.write_text(json.dumps(terminal), encoding="utf-8")

    with pytest.raises(OracleFormatError):
        grade_source_owned_ast_evidence(request)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "divergent"])
def test_source_owned_ast_categories_hold_snapshot_drift(mutation: str) -> None:
    """Hold missing, extra, duplicate and cross-backend AST fact rows.

    Parameters
    ----------
    mutation : str
        Snapshot mutation applied to one backend.

    Returns
    -------
    None
    """
    source, source_path, normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    if mutation == "missing":
        rows["sqlite"]["fields"] = []
    elif mutation == "extra":
        cast("list[JSONValue]", rows["sqlite"]["declarations"]).append(
            {"kind": "struct", "line": 1, "name": "extra"}
        )
        rows["duckdb"]["declarations"] = rows["sqlite"]["declarations"]
    elif mutation == "duplicate":
        callables = cast("list[JSONValue]", rows["sqlite"]["callables"])
        callables.append(callables[0])
        rows["duckdb"]["callables"] = callables
    else:
        rows["duckdb"]["fields"] = []
    report = grade_source_owned_ast_categories(
        normalized, raw_ast, source, capabilities, rows, normalizer, cwd
    )
    categories = cast("dict[str, JSONValue]", report["categories"])
    expected = (
        "fields"
        if mutation in {"missing", "divergent"}
        else ("callables" if mutation == "duplicate" else "declarations")
    )
    assert cast("dict[str, JSONValue]", categories[expected])["state"] == "held"
    assert report["whole_file_admission"] is False


def test_source_owned_ast_categories_reject_fabricated_coordinates_and_scope() -> None:
    """Reject invented coordinates and non-local excluded variables.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source, source_path, normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    facts = cast("dict[str, JSONValue]", normalized["facts"])
    declarations = cast("list[JSONValue]", facts["declarations"])
    cast("dict[str, JSONValue]", declarations[0])["column"] = 99
    with pytest.raises(OracleFormatError, match="does not equal a fresh replay"):
        grade_source_owned_ast_categories(
            normalized, raw_ast, source, capabilities, rows, normalizer, cwd
        )

    source, source_path, normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    ast_children = cast("list[object]", raw_ast["inner"])
    function = cast("dict[str, object]", ast_children[1])
    compound = cast("dict[str, object]", cast("list[object]", function["inner"])[0])
    compound["inner"] = []
    ast_children.append(
        {
            "kind": "VarDecl",
            "name": "local",
            "type": {"qualType": "int"},
            "loc": {
                "file": str(source_path),
                "line": 2,
                "col": source.index(b"local")
                - source.rfind(b"\n", 0, source.index(b"local")),
                "offset": source.index(b"local"),
                "tokLen": 5,
            },
        }
    )
    normalized = cast(
        "dict[str, JSONValue]", normalize_ast(raw_ast, source_path, source, cwd)
    )
    with pytest.raises(OracleFormatError, match="file-scope variable"):
        grade_source_owned_ast_categories(
            normalized, raw_ast, source, capabilities, rows, normalizer, cwd
        )


def test_source_owned_ast_categories_reject_omitted_normalized_inventory() -> None:
    """Reject deletion from normalized expectations and matching snapshots.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source, _source_path, normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    facts = cast("dict[str, JSONValue]", normalized["facts"])
    declarations = cast("list[JSONValue]", facts["declarations"])
    facts["declarations"] = [
        row
        for row in declarations
        if cast("dict[str, JSONValue]", row).get("kind") != "FunctionDecl"
    ]
    facts["callables"] = []
    rows["sqlite"]["callables"] = []
    rows["duckdb"]["callables"] = []
    with pytest.raises(OracleFormatError, match="fresh replay"):
        grade_source_owned_ast_categories(
            normalized, raw_ast, source, capabilities, rows, normalizer, cwd
        )


@pytest.mark.parametrize(
    "mutation", ["field_type", "field_owner", "record_tag", "function_signature"]
)
def test_source_owned_ast_categories_reconcile_raw_type_owner_and_tag(
    mutation: str,
) -> None:
    """Use raw AST types, lexical owners and tag kinds as expectations.

    Parameters
    ----------
    mutation : str
        Raw AST ownership, type or tag mutation.

    Returns
    -------
    None
    """
    source, source_path, _normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    children = cast("list[object]", raw_ast["inner"])
    record = cast("dict[str, object]", children[0])
    record_children = cast("list[object]", record["inner"])
    field = cast("dict[str, object]", record_children[0])
    function = cast("dict[str, object]", children[1])
    if mutation == "field_type":
        cast("dict[str, object]", field["type"])["qualType"] = "long"
    elif mutation == "field_owner":
        record["inner"] = []
        children.append(field)
    elif mutation == "record_tag":
        record["tagUsed"] = "union"
    else:
        cast("dict[str, object]", function["type"])["qualType"] = "char (struct R *)"
    normalized = cast(
        "dict[str, JSONValue]", normalize_ast(raw_ast, source_path, source, cwd)
    )
    if mutation == "field_owner":
        with pytest.raises(
            OracleFormatError, match="owner and type must be source-proven"
        ):
            grade_source_owned_ast_categories(
                normalized, raw_ast, source, capabilities, rows, normalizer, cwd
            )
        return
    report = grade_source_owned_ast_categories(
        normalized, raw_ast, source, capabilities, rows, normalizer, cwd
    )
    category = (
        "fields"
        if mutation == "field_type"
        else ("declarations" if mutation == "record_tag" else "callables")
    )
    categories = cast("dict[str, JSONValue]", report["categories"])
    assert cast("dict[str, JSONValue]", categories[category])["state"] == "held"
    assert report["whole_file_admission"] is False


def test_source_owned_ast_categories_reject_identifier_prefix_anchor() -> None:
    """Reject a declaration spelling that is only a token prefix.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source, source_path, _normalized, raw_ast, capabilities, rows, normalizer, cwd = (
        _source_owned_ast_fixture()
    )
    changed_source = source.replace(b"struct R", b"struct RX", 1)
    normalized = cast(
        "dict[str, JSONValue]",
        normalize_ast(raw_ast, source_path, changed_source, cwd),
    )
    with pytest.raises(OracleFormatError, match="ungraded_declarations"):
        grade_source_owned_ast_categories(
            normalized, raw_ast, changed_source, capabilities, rows, normalizer, cwd
        )


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal", ".wal"])
def test_database_generation_binding_rejects_active_sidecar(
    tmp_path: Path, suffix: str
) -> None:
    """Reject a database whose live sidecar is outside the immutable hash.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary test directory.
    suffix : str
        Database journal or sidecar suffix.

    Returns
    -------
    None
    """
    database = tmp_path / "index.db"
    database.write_bytes(b"database")
    Path(f"{database}{suffix}").write_bytes(b"active database sidecar")

    with pytest.raises(OracleFormatError, match="active database sidecars"):
        _database_generation_binding(database, "sqlite")


def test_source_key_must_identify_guarded_source_path(tmp_path: Path) -> None:
    """Reject another path with matching bytes as the selected snapshot case.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated temporary test directory.

    Returns
    -------
    None
    """
    root = tmp_path / "source-root"
    source = root / "src" / "unit.c"
    source.parent.mkdir(parents=True)
    source.write_text("int x;\n", encoding="utf-8")

    _validate_source_key(source, "src/unit.c", root)
    with pytest.raises(OracleFormatError, match="does not equal"):
        _validate_source_key(source, "other/unit.c", root)
