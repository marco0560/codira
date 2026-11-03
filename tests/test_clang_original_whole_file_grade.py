"""Contract checks for bound whole-file grade inputs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from scripts.clang_original_whole_file_grade import (
    SOURCE_FACT_CATEGORIES,
    GradeRequest,
    _canonical,
    _read_actual_analysis_status,
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
    grade_contract,
)
from scripts.clang_parity_qualification import (
    FACT_CATEGORIES,
    OracleFormatError,
    _source_macro_invocation_span,
)
from scripts.clang_reference_facts import REQUIRED_CATEGORIES

if TYPE_CHECKING:
    from pathlib import Path

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


def _run_grade_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    held_category: str | None = None,
    diverge_backend: bool = False,
    inject_negative_control: bool = False,
) -> dict[str, JSONValue]:
    """Run grade_contract with only external database/profile readers stubbed."""
    source = tmp_path / "fixture.cpp"
    source.write_text("int value;\n", encoding="utf-8")
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
                "state": "held" if category == held_category else "graded",
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
    assert set(held_categories) == set(FACT_CATEGORIES) - {"coverage"}
    assert report["held_category_count"] == len(held_categories)


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
