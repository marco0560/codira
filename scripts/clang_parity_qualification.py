"""Validate source-authored Clang parity oracles and grade backend snapshots.

The oracle stays independent of analyzer output: expected facts come from the
fixture source files, while a backend snapshot is a deterministic projection of
persisted Codira rows.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sqlite3
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

from codira.generated import generated_provenance_payload

if TYPE_CHECKING:
    from types import ModuleType

type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


class OracleFormatError(ValueError):
    """Invalid oracle or persisted snapshot structure."""

    def __init__(self, context: str, requirement: str) -> None:
        """Describe a failed structural requirement.

        Parameters
        ----------
        context : str
            Oracle or snapshot location where validation failed.
        requirement : str
            Required structure or value that was missing.
        """
        super().__init__(f"{context}: {requirement}")


def _raise_format_error(context: str, requirement: str) -> NoReturn:
    """Raise a consistently formatted oracle validation error.

    Parameters
    ----------
    context : str
        Oracle or snapshot location where validation failed.
    requirement : str
        Required structure or value that was missing.

    Raises
    ------
    OracleFormatError
        Always, with the supplied context and requirement.
    """
    raise OracleFormatError(context, requirement)


FACT_CATEGORIES = (
    "includes",
    "declarations",
    "fields",
    "enum_members",
    "types",
    "coverage",
    "callables",
    "documentation",
    "calls",
    "external_owners",
    "forbidden_artifacts",
    "generated_declarations",
)


@dataclass(frozen=True)
class OracleCase:
    """One source file and its expected semantic facts."""

    source: str
    language: str
    facts: dict[str, tuple[dict[str, JSONValue], ...]]
    pending_facts: dict[str, tuple[dict[str, JSONValue], ...]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class OracleDocument:
    """Versioned source-authored expected facts."""

    cases: dict[str, OracleCase]
    header_context_requests: tuple[dict[str, JSONValue], ...] = ()
    identity_invariants: tuple[dict[str, JSONValue], ...] = ()
    identity_observation_requests: tuple[dict[str, JSONValue], ...] = ()


@dataclass(frozen=True)
class GradeFailure:
    """One expected fact missing or contradicted by persisted output."""

    case: str
    category: str
    expected: dict[str, JSONValue]
    reason: str


@dataclass(frozen=True)
class FreezeDifference:
    """One frozen input or public constant that changed."""

    key: str
    expected: JSONValue
    actual: JSONValue


@dataclass(frozen=True)
class ProfilePreparationRequest:
    """Explicit inputs for one generic batch of prepared profiles."""

    sources: list[Path]
    repository_root: Path
    compile_database: Path
    helper_path: Path
    build_receipt_path: Path
    output_directory: Path
    attempt_prefix: str


@dataclass(frozen=True)
class DatabaseSnapshotRows:
    """Typed raw-table index used while projecting one backend snapshot.

    Attributes
    ----------
    file_paths : dict[int, str]
        Oracle-relative source paths keyed by persisted file ID.
    file_ids_by_path : dict[str, int]
        Persisted file IDs keyed by exact oracle-relative path.
    file_hashes : dict[int, str]
        Persisted source hashes keyed by file ID.
    source_bytes_by_file : dict[int, bytes]
        Current verified source bytes keyed by file ID.
    analysis_input_fingerprints : dict[int, str]
        Exact outer analyzer input identities keyed by file ID.
    symbols_by_id : dict[str, dict[str, Any]]
        Symbol rows keyed by stable ID.
    symbols_by_file : dict[int, list[dict[str, Any]]]
        Symbol rows grouped by physical source file.
    callable_identities : dict[tuple[str, str], list[str]]
        Callable stable IDs keyed by exact semantic identity.
    modules : dict[int, dict[str, Any]]
        Module rows keyed by module ID.
    classes : list[dict[str, Any]]
        Class rows with physical file identity added.
    functions : list[dict[str, Any]]
        Persisted function and method rows.
    overloads : list[dict[str, Any]]
        Persisted overload declarations attached to canonical callable rows.
    imports : list[dict[str, Any]]
        Persisted import and include rows.
    enum_members : list[dict[str, Any]]
        Persisted enumeration member rows.
    documentation : list[dict[str, Any]]
        Persisted documentation rows.
    edges : list[dict[str, Any]]
        Persisted call edge rows.
    calls : list[dict[str, Any]]
        Persisted raw call record rows.
    provenance_by_stable_id : dict[str, dict[str, object]]
        Strictly validated generated provenance keyed by artifact stable ID.
    """

    file_paths: dict[int, str]
    file_ids_by_path: dict[str, int]
    file_hashes: dict[int, str]
    source_bytes_by_file: dict[int, bytes]
    analysis_input_fingerprints: dict[int, str]
    symbols_by_id: dict[str, dict[str, Any]]
    symbols_by_file: dict[int, list[dict[str, Any]]]
    callable_identities: dict[tuple[str, str], list[str]]
    modules: dict[int, dict[str, Any]]
    classes: list[dict[str, Any]]
    functions: list[dict[str, Any]]
    overloads: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    enum_members: list[dict[str, Any]]
    documentation: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    provenance_by_stable_id: dict[str, dict[str, object]]


@dataclass(frozen=True)
class ProjectedSnapshotRows:
    """Category rows prepared from one backend database.

    Attributes
    ----------
    database : DatabaseSnapshotRows
        Raw persisted rows and source indexes.
    callables : dict[tuple[int, int, str], dict[str, JSONValue]]
        Persisted function and method rows.
    includes : dict[int, list[dict[str, JSONValue]]]
        Include rows grouped by file.
    enum_members : dict[int, list[dict[str, JSONValue]]]
        Enum members grouped by file.
    documentation : dict[int, list[dict[str, JSONValue]]]
        Documentation rows grouped by file.
    calls : dict[int, list[dict[str, JSONValue]]]
        Call rows grouped by file.
    """

    database: DatabaseSnapshotRows
    callables: dict[tuple[int, int, str], dict[str, JSONValue]]
    includes: dict[int, list[dict[str, JSONValue]]]
    enum_members: dict[int, list[dict[str, JSONValue]]]
    documentation: dict[int, list[dict[str, JSONValue]]]
    calls: dict[int, list[dict[str, JSONValue]]]


@dataclass(frozen=True)
class GeneratedDeclarationInput:
    """Database-owned row coordinates for one generated declaration.

    Parameters
    ----------
    stable_id : str
        Artifact identity used to load its persisted compiler evidence.
    name : str
        Persisted source-qualified declaration name.
    line : int
        Source line stored for the declaration.
    source : str
        Repository-relative physical source path.
    file_id : int
        Persisted source file ID used to bind receipt digests and context.
    symbol : dict[str, Any] or None
        Matching callable symbol row, when one exists.

    Returns
    -------
    None
        Immutable projection input used by the snapshot exporter.
    """

    stable_id: str
    name: str
    line: int
    source: str
    file_id: int
    symbol: dict[str, Any] | None


def _object(value: JSONValue, context: str) -> dict[str, JSONValue]:
    """Require one JSON object.

    Parameters
    ----------
    value : JSONValue
        Value to validate.
    context : str
        Path included in a validation error.

    Returns
    -------
    dict[str, JSONValue]
        Validated object value.
    """
    if not isinstance(value, dict):
        _raise_format_error(context, "must be a JSON object")
    return value


def _array(value: JSONValue, context: str) -> list[JSONValue]:
    """Require one JSON array.

    Parameters
    ----------
    value : JSONValue
        Value to validate.
    context : str
        Path included in a validation error.

    Returns
    -------
    list[JSONValue]
        Validated array value.
    """
    if not isinstance(value, list):
        _raise_format_error(context, "must be a JSON array")
    return value


def _string(value: JSONValue, context: str) -> str:
    """Require one non-empty JSON string.

    Parameters
    ----------
    value : JSONValue
        Value to validate.
    context : str
        Path included in a validation error.

    Returns
    -------
    str
        Validated string value.
    """
    if not isinstance(value, str) or not value:
        _raise_format_error(context, "must be a non-empty string")
    return value


def load_oracle(path: Path, fixture_root: Path) -> OracleDocument:
    """Load and validate a source oracle against its physical fixture files.

    Parameters
    ----------
    path : pathlib.Path
        JSON oracle document.
    fixture_root : pathlib.Path
        Directory containing all source files named by the oracle.

    Returns
    -------
    OracleDocument
        Typed oracle with exact source names and coordinates preserved.

    Raises
    ------
    ValueError
        If the oracle is malformed or points outside/misses its fixture tree.
    """
    raw_value: JSONValue = json.loads(path.read_text(encoding="utf-8"))
    raw = _object(raw_value, "oracle")
    if raw.get("oracle_version") != 1 or raw.get("source_authored_oracle") is not True:
        _raise_format_error("oracle", "must be source-authored version 1")
    raw_cases = _object(raw.get("cases"), "oracle.cases")
    parsed: dict[str, OracleCase] = {}
    for source, case_value in raw_cases.items():
        source = _string(source, "case source")
        case = _object(case_value, f"case {source}")
        language = _string(case.get("language"), f"case {source}.language")
        source_path = (fixture_root / source).resolve()
        if (
            not source_path.is_relative_to(fixture_root.resolve())
            or not source_path.is_file()
        ):
            _raise_format_error(
                "case source", f"missing or outside fixture root: {source}"
            )
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
        source_bytes = source_path.read_bytes()
        facts: dict[str, tuple[dict[str, JSONValue], ...]] = {}
        for category in FACT_CATEGORIES:
            values = case.get(category, [])
            if not isinstance(values, list):
                _raise_format_error(f"case {source}.{category}", "must be an array")
            rows: list[dict[str, JSONValue]] = []
            for index, value in enumerate(values):
                row = _object(value, f"case {source}.{category}[{index}]")
                _validate_source_coordinates(
                    row, source, f"{source}.{category}[{index}]", len(source_lines)
                )
                if row.get("generated") is True:
                    _validate_generated_invocation(
                        row, source, source_path, source_bytes, len(source_lines)
                    )
                if category == "generated_declarations":
                    _validate_generated_declaration_source(
                        row, source, source_path, source_bytes, len(source_lines)
                    )
                rows.append(row)
            facts[category] = tuple(rows)
        nested_enum_members = _nested_enum_members(facts["declarations"], source)
        if nested_enum_members:
            facts["enum_members"] = tuple(
                [*facts["enum_members"], *nested_enum_members]
            )
        pending_facts = _parse_pending_facts(
            case, source, source_path, source_bytes, len(source_lines)
        )
        parsed[source] = OracleCase(
            source=source,
            language=language,
            facts=facts,
            pending_facts=pending_facts,
        )
    header_requests = _global_rows(
        raw.get("header_context_requests", []), "header_context_requests"
    )
    invariants = _global_rows(raw.get("identity_invariants", []), "identity_invariants")
    identity_requests = _global_rows(
        raw.get("identity_observation_requests", []),
        "identity_observation_requests",
    )
    known_sources = parsed.keys()
    for request in header_requests:
        header_path = _string(request.get("path"), "header context path")
        resolved_header = (fixture_root / header_path).resolve()
        if (
            not resolved_header.is_relative_to(fixture_root.resolve())
            or not resolved_header.is_file()
        ):
            _raise_format_error(
                "header context path", f"missing or outside fixture root: {header_path}"
            )
        owners = request.get("owners", [])
        if not isinstance(owners, list) or any(
            not isinstance(owner, str) or owner not in known_sources for owner in owners
        ):
            _raise_format_error(
                header_path, "owners must name oracle translation units"
            )
    return OracleDocument(parsed, header_requests, invariants, identity_requests)


def _parse_pending_facts(
    case: dict[str, JSONValue],
    source: str,
    source_path: Path,
    source_bytes: bytes,
    line_count: int,
) -> dict[str, tuple[dict[str, JSONValue], ...]]:
    """Validate source-bound pending assertions for one case.

    Parameters
    ----------
    case : dict[str, JSONValue]
        Parsed source-oracle case object.
    source : str
        Oracle-relative source path.
    source_path : pathlib.Path
        Physical source path for invocation validation.
    source_bytes : bytes
        Exact source bytes for generated invocation spans.
    line_count : int
        Number of physical source lines.

    Returns
    -------
    dict[str, tuple[dict[str, JSONValue], ...]]
        Validated pending facts grouped by category.
    """
    raw_pending = _object(case.get("pending", {}), f"case {source}.pending")
    pending_facts: dict[str, tuple[dict[str, JSONValue], ...]] = {}
    for category, values in raw_pending.items():
        if category not in FACT_CATEGORIES or not isinstance(values, list):
            _raise_format_error(
                f"case {source}.pending.{category}", "must be a known fact array"
            )
        pending_rows: list[dict[str, JSONValue]] = []
        for index, value in enumerate(values):
            row = _object(value, f"case {source}.pending.{category}[{index}]")
            _validate_source_coordinates(
                row, source, f"{source}.pending.{category}[{index}]", line_count
            )
            if row.get("generated") is True:
                _validate_generated_invocation(
                    row, source, source_path, source_bytes, line_count
                )
            if category == "generated_declarations":
                _validate_generated_declaration_source(
                    row, source, source_path, source_bytes, line_count
                )
            pending_rows.append(row)
        pending_facts[category] = tuple(pending_rows)
    return pending_facts


def _validate_generated_declaration_source(
    row: dict[str, JSONValue],
    source: str,
    path: Path,
    source_bytes: bytes,
    line_count: int,
) -> None:
    """Bind alias and implementation expectations to their macro spelling.

    Parameters
    ----------
    row : dict[str, JSONValue]
        Source-authored generated declaration expectation.
    source : str
        Oracle-relative source path.
    path : pathlib.Path
        Physical source fixture path.
    source_bytes : bytes
        Exact UTF-8 bytes read from the source fixture.
    line_count : int
        Number of physical source lines.

    Returns
    -------
    None
        Source evidence is validated in place without adding inferred facts.

    Raises
    ------
    ValueError
        If a macro invocation, expansion expression, or source argument differs.
    """
    evidence = _object(row.get("source_evidence"), f"{source}.source_evidence")
    macro = _string(evidence.get("macro"), f"{source}.source_evidence.macro")
    invocation_line = evidence.get("invocation_line")
    definition_line = evidence.get("macro_definition_line")
    argument = _string(evidence.get("argument"), f"{source}.source_evidence.argument")
    expression = _string(
        evidence.get("macro_expression"), f"{source}.source_evidence.macro_expression"
    )
    span = evidence.get("invocation_span")
    if (
        not isinstance(invocation_line, int)
        or isinstance(invocation_line, bool)
        or not 1 <= invocation_line <= line_count
        or not isinstance(definition_line, int)
        or isinstance(definition_line, bool)
        or not 1 <= definition_line <= line_count
    ):
        _raise_format_error(source, "generated declaration lines are outside source")
    if row.get("line") != invocation_line:
        _raise_format_error(
            source, "generated declaration line must name its invocation"
        )
    if (
        not isinstance(span, list)
        or len(span) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in span)
        or span != list(_source_macro_invocation_span(path, macro, invocation_line))
    ):
        _raise_format_error(
            source, "generated declaration invocation span differs from source"
        )
    expected = cast("list[int]", span)
    invocation = source_bytes[expected[0] : expected[1]].decode("utf-8")
    macro_definition = path.read_text(encoding="utf-8").splitlines()[
        definition_line - 1
    ]
    if expression not in macro_definition:
        _raise_format_error(
            source, "generated declaration expression differs from source"
        )
    arguments = _macro_invocation_arguments(invocation, macro)
    argument_index = (
        1
        if len(arguments) > 1
        and expression
        in {
            "asm(#N)",
            "[[gnu::alias(#N)]]",
        }
        else 0
    )
    if len(arguments) <= argument_index or arguments[argument_index] != argument:
        _raise_format_error(
            source, "generated declaration argument differs from source"
        )
    role = _string(row.get("role"), f"{source}.generated declaration role")
    name = _string(row.get("name"), f"{source}.generated declaration name")
    expected_suffix = (
        f"impl_{argument}"
        if expression == "asm(#N)" and role in {"prototype", "definition"}
        else argument
    )
    if name.rsplit("::", 1)[-1] != expected_suffix:
        _raise_format_error(
            source, "generated declaration name differs from its macro argument"
        )
    if (
        expression == "asm(#N)"
        and row.get("linkage_name") is not None
        and row.get("linkage_name") != argument
    ):
        _raise_format_error(
            source, "linkage label is not the stringified macro argument"
        )
    if (
        expression == "[[gnu::alias(#N)]]"
        and row.get("alias_target_symbol") != argument
    ):
        _raise_format_error(
            source, "alias target operand is not the stringified macro argument"
        )


def _macro_invocation_arguments(invocation: str, macro: str) -> list[str]:
    """Split the authored macro arguments while respecting nested parentheses.

    Parameters
    ----------
    invocation : str
        Exact physical invocation text.
    macro : str
        Expected macro name at the start of the invocation.

    Returns
    -------
    list[str]
        Macro arguments in authored order, retaining nested type expressions.

    Raises
    ------
    ValueError
        If the invocation has no balanced argument list.
    """
    start = invocation.find(macro)
    opening = invocation.find("(", start + len(macro))
    if start < 0 or opening < 0 or not invocation.rstrip().endswith(")"):
        _raise_format_error(macro, "source macro invocation is malformed")
    depth = 0
    arguments: list[str] = []
    argument_start = opening + 1
    for index in range(opening + 1, len(invocation)):
        character = invocation[index]
        if character == "(":
            depth += 1
        elif character == ")":
            if depth == 0:
                arguments.append(invocation[argument_start:index].strip())
                if invocation[index + 1 :].strip():
                    _raise_format_error(macro, "text follows source macro invocation")
                return arguments
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(invocation[argument_start:index].strip())
            argument_start = index + 1
    _raise_format_error(macro, "source macro invocation is unbalanced")


def _nested_enum_members(
    declarations: tuple[dict[str, JSONValue], ...], source: str
) -> list[dict[str, JSONValue]]:
    """Collect source-authored enum members nested inside declarations.

    Parameters
    ----------
    declarations : tuple[dict[str, JSONValue], ...]
        Parsed declaration rows for one source file.
    source : str
        Oracle-relative source path for validation context.

    Returns
    -------
    list[dict[str, JSONValue]]
        Nested member rows for grading against the normalized member table.
    """
    members: list[dict[str, JSONValue]] = []
    for declaration in declarations:
        raw_members = declaration.get("enum_members")
        if isinstance(raw_members, list):
            members.extend(
                _object(member, f"{source}.declaration.enum_members")
                for member in raw_members
            )
    return members


def _validate_source_coordinates(
    value: JSONValue, source: str, context: str, source_line_count: int
) -> None:
    """Validate all direct and nested source line fields.

    Parameters
    ----------
    value : JSONValue
        Fact or nested value to inspect.
    source : str
        Oracle-relative source path for error messages.
    context : str
        Current JSON location for error messages.
    source_line_count : int
        Number of physical lines in the source file.

    Returns
    -------
    None
        Validation completes without returning a value.
    """
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("_line") or key == "line":
                if not isinstance(child, int) or isinstance(child, bool):
                    _raise_format_error(f"{context}.{key}", "must be an integer")
                if not 1 <= child <= source_line_count:
                    _raise_format_error(f"{context}.{key}", f"is outside {source}")
            _validate_source_coordinates(
                child, source, f"{context}.{key}", source_line_count
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_source_coordinates(
                child, source, f"{context}[{index}]", source_line_count
            )


def _global_rows(value: JSONValue, context: str) -> tuple[dict[str, JSONValue], ...]:
    """Parse source-oracle metadata arrays.

    Parameters
    ----------
    value : JSONValue
        Candidate array value.
    context : str
        Oracle location included in validation errors.

    Returns
    -------
    tuple[dict[str, JSONValue], ...]
        Validated object rows.
    """
    if not isinstance(value, list):
        _raise_format_error(context, "must be an array")
    return tuple(
        _object(item, f"{context}[{index}]") for index, item in enumerate(value)
    )


def _validate_generated_invocation(
    row: dict[str, JSONValue],
    source: str,
    path: Path,
    source_bytes: bytes,
    line_count: int,
) -> None:
    """Bind generated callable expectations to an authored macro invocation.

    Parameters
    ----------
    row : dict[str, JSONValue]
        Expected generated callable facts.
    source : str
        Oracle-relative source path.
    path : pathlib.Path
        Physical fixture source path.
    source_bytes : bytes
        Exact source bytes used to validate the invocation span.
    line_count : int
        Physical source line count.

    Returns
    -------
    None
        Validation completes without returning a value.
    """
    macro = _string(row.get("generated_macro"), f"{source}.generated_macro")
    line = row.get("invocation_line")
    span = row.get("generated_invocation_span")
    if (
        not isinstance(line, int)
        or isinstance(line, bool)
        or not 1 <= line <= line_count
    ):
        _raise_format_error(
            source, "generated callable needs an in-range invocation_line"
        )
    if (
        not isinstance(span, list)
        or len(span) != 2
        or any(
            not isinstance(offset, int) or isinstance(offset, bool) for offset in span
        )
    ):
        _raise_format_error(
            source, "generated_invocation_span must be two byte offsets"
        )
    span_values = cast("list[int]", span)
    expected_span = _source_macro_invocation_span(path, macro, line)
    if span_values != list(expected_span):
        _raise_format_error(
            source, f"generated invocation span differs from {macro} source"
        )
    if source_bytes[span_values[0] : span_values[1]].decode(
        "utf-8"
    ) != _source_macro_invocation_text(path, macro, line):
        _raise_format_error(
            source, "generated invocation span does not match source bytes"
        )
    row["generated_invocation_text"] = source_bytes[
        span_values[0] : span_values[1]
    ].decode("utf-8")
    expected_name = _string(row.get("name"), f"{source}.generated callable name")
    if expected_name.rsplit("::", 1)[-1] not in source_bytes[
        span_values[0] : span_values[1]
    ].decode("utf-8"):
        _raise_format_error(source, "generated callable name is not a macro argument")


def _source_macro_invocation_span(path: Path, macro: str, line: int) -> tuple[int, int]:
    """Find the byte span of one balanced, source-written macro invocation.

    Parameters
    ----------
    path : pathlib.Path
        Physical fixture source path.
    macro : str
        Macro identifier expected on the requested line.
    line : int
        One-based source line containing the invocation.

    Returns
    -------
    tuple[int, int]
        Half-open UTF-8 byte offsets for the invocation.
    """
    lines = path.read_bytes().splitlines(keepends=True)
    line_bytes = lines[line - 1]
    line_text = line_bytes.decode("utf-8")
    start_in_line = line_text.find(macro)
    open_paren = line_text.find("(", start_in_line + len(macro))
    if start_in_line < 0 or open_paren < 0:
        _raise_format_error(path.name, f"line {line} has no invocation of {macro}")
    depth = 0
    close_paren = -1
    for index in range(open_paren, len(line_text)):
        if line_text[index] == "(":
            depth += 1
        elif line_text[index] == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren < 0:
        _raise_format_error(
            path.name, f"line {line} has an unterminated {macro} invocation"
        )
    line_offset = sum(len(item) for item in lines[: line - 1])
    return line_offset + start_in_line, line_offset + close_paren + 1


def _source_macro_invocation_text(path: Path, macro: str, line: int) -> str:
    """Return one exact source macro invocation without surrounding code.

    Parameters
    ----------
    path : pathlib.Path
        Physical fixture source path.
    macro : str
        Macro identifier expected on the requested line.
    line : int
        One-based source line containing the invocation.

    Returns
    -------
    str
        Exact invocation text from the source bytes.
    """
    start, end = _source_macro_invocation_span(path, macro, line)
    return path.read_bytes()[start:end].decode("utf-8")


def _matches(
    expected: dict[str, JSONValue],
    observed: dict[str, JSONValue],
    category: str,
    source_sha256: str | None = None,
) -> bool:
    """Match exact oracle dimensions without normalizing names or identity.

    Parameters
    ----------
    expected : dict[str, JSONValue]
        Source-authored dimensions to require.
    observed : dict[str, JSONValue]
        Persisted row dimensions to compare.
    category : str
        Fact category controlling explicit field mappings.
    source_sha256 : str or None, optional
        Frozen source digest required for generated provenance.

    Returns
    -------
    bool
        Whether every asserted dimension matches exactly.
    """
    if category == "calls" and not _matches_call_resolution(expected, observed):
        return False
    if (
        category == "callables"
        and expected.get("generated") is True
        and not _matches_generated_callable(expected, observed, source_sha256)
    ):
        return False
    for key, value in expected.items():
        if key in {
            "resolution",
            "prototype_line",
            "invocation",
            "target_identity_must_differ_from",
            "generated_macro",
            "generated_invocation_span",
            "generated_spelling_line",
            "generated_invocation_text",
            "source_evidence",
            "identity_reference",
            "compiler_identity_reference",
            "alias_target_identity_reference",
        }:
            continue
        persisted_key = key
        if category == "callables" and key == "invocation_line":
            persisted_key = "generated_invocation_line"
        if category == "calls":
            persisted_key = {
                "caller": "caller_qualified_name",
                "target": (
                    "unresolved_target_qualified_name"
                    if observed.get("resolved") is False
                    else "callee_qualified_name"
                ),
                "definition_line": "callee_definition_line",
                "defined_in": "callee_source",
            }.get(key, key)
        if observed.get(persisted_key) != value:
            return False
    return True


def _matches_generated_callable(
    expected: dict[str, JSONValue],
    observed: dict[str, JSONValue],
    source_sha256: str | None,
) -> bool:
    """Check persisted compiler-origin provenance without inventing token ops.

    Parameters
    ----------
    expected : dict[str, JSONValue]
        Source-authored generated callable dimensions.
    observed : dict[str, JSONValue]
        Persisted callable row and provenance.
    source_sha256 : str or None
        Frozen source digest associated with this case.

    Returns
    -------
    bool
        Whether provenance is complete and bound to this source invocation.
    """
    provenance = observed.get("generated_provenance")
    if not isinstance(provenance, dict):
        return False
    invocation = provenance.get("invocation")
    expected_span = expected.get("generated_invocation_span")
    if (
        provenance.get("variant") != "compiler_observed"
        or provenance.get("origin") not in {"macro_argument", "macro_replacement"}
        or provenance.get("role") != "definition"
        or observed.get("source_kind") != "compiler_generated"
        or not isinstance(invocation, dict)
        or invocation.get("byte_range") != expected_span
        or invocation.get("name") != expected.get("generated_macro")
        or invocation.get("text") != expected.get("generated_invocation_text")
    ):
        return False
    if (
        not isinstance(source_sha256, str)
        or not source_sha256
        or provenance.get("source_sha256") != source_sha256
        or observed.get("source_sha256") != source_sha256
        or not isinstance(provenance.get("context_identity"), str)
        or not provenance.get("context_identity")
        or provenance.get("context_identity")
        != observed.get("outer_analysis_input_fingerprint")
        or observed.get("generated_invocation_line") != expected.get("invocation_line")
    ):
        return False
    spelling_location = provenance.get("physical_spelling_location")
    # V2 stores compiler facts in the receipt; the body spelling start is the
    # callable span's begin.spelling coordinate, not its source-written name.
    receipt_text = provenance.get("receipt_json")
    if not isinstance(receipt_text, str):
        return False
    try:
        receipt: JSONValue = json.loads(receipt_text)
    except json.JSONDecodeError:
        return False
    if not isinstance(receipt, dict):
        return False
    context = receipt.get("context")
    callable_record = receipt.get("callable")
    if not isinstance(context, dict) or not isinstance(callable_record, dict):
        return False
    span = callable_record.get("span")
    if not isinstance(span, dict) or not isinstance(span.get("begin"), dict):
        return False
    begin = cast("dict[str, JSONValue]", span["begin"])
    spelling_location = begin.get("spelling")
    if not isinstance(spelling_location, dict):
        return False
    expected_spelling_line = expected.get("generated_spelling_line")
    compiler_identity_ref = observed.get("compiler_identity_ref")
    compiler_usr = callable_record.get("usr")
    stdout_sha256 = context.get("stdout_sha256")
    return (
        spelling_location.get("line") == expected_spelling_line
        and isinstance(compiler_identity_ref, str)
        and compiler_identity_ref == f"clang.usr.v1:{compiler_usr}"
        and context.get("analyzer_context_identity")
        == provenance.get("context_identity")
        and context.get("source_sha256") == source_sha256
        and isinstance(stdout_sha256, str)
        and stdout_sha256 == observed.get("compiler_stdout_sha256")
        and re.fullmatch(r"[0-9a-f]{64}", stdout_sha256) is not None
    )


def _matches_call_resolution(
    expected: dict[str, JSONValue], observed: dict[str, JSONValue]
) -> bool:
    """Check exact call identity and resolved or unresolved state.

    Parameters
    ----------
    expected : dict[str, JSONValue]
        Source-authored target and call location.
    observed : dict[str, JSONValue]
        Persisted exact call row.

    Returns
    -------
    bool
        Whether call identity state matches the oracle.
    """
    unresolved = expected.get("resolution") in {
        "external_or_unindexed",
        "indirect_unresolved",
        "internal_header_unresolved_until_header_projection",
    }
    if unresolved:
        if (
            observed.get("resolved") is not False
            or observed.get("callee_stable_id") is not None
        ):
            return False
    elif observed.get("resolved") is not True or not observed.get("callee_stable_id"):
        return False
    if not observed.get("caller_stable_id"):
        return False
    if observed.get("resolution_mode") != "exact":
        return False
    return expected.get("resolution") == "indirect_unresolved" or bool(
        observed.get("target_identity_namespace")
        and observed.get("target_identity_value")
    )


def grade_snapshot(
    oracle: OracleDocument, snapshot: dict[str, JSONValue]
) -> tuple[GradeFailure, ...]:
    """Compare a persisted backend snapshot with all source-authored facts.

    Parameters
    ----------
    oracle : OracleDocument
        Expected facts tied to authored source files.
    snapshot : dict[str, JSONValue]
        Snapshot with ``snapshot_version``, ``backend``, and per-case category
        arrays. Every expected row must match one observed row exactly on all
        asserted fields. Display-name normalization is never applied.

    Returns
    -------
    tuple[GradeFailure, ...]
        Empty when all expected facts are present and exact.
    """
    if snapshot.get("snapshot_version") != 1:
        _raise_format_error("snapshot_version", "is unsupported")
    if snapshot.get("backend") not in {"sqlite", "duckdb"}:
        _raise_format_error("snapshot backend", "must be sqlite or duckdb")
    raw_cases = _object(snapshot.get("cases"), "snapshot.cases")
    failures = _grade_cases(oracle, raw_cases)
    identity_observations = _generated_declaration_identity_observations(
        oracle, raw_cases
    )
    recorded_observations = _object(
        snapshot.get("identity_observations", {}), "snapshot.identity_observations"
    )
    merged_snapshot = dict(snapshot)
    merged_snapshot["identity_observations"] = {
        **recorded_observations,
        **identity_observations,
    }
    failures.extend(_grade_global_metadata(oracle, merged_snapshot))
    return tuple(failures)


def _generated_declaration_identity_observations(
    oracle: OracleDocument, raw_cases: dict[str, JSONValue]
) -> dict[str, JSONValue]:
    """Read source-requested declaration and alias-target identities.

    Parameters
    ----------
    oracle : OracleDocument
        Authored declaration roles and identity references.
    raw_cases : dict[str, JSONValue]
        Per-source persisted snapshot rows.

    Returns
    -------
    dict[str, JSONValue]
        Compiler identities keyed by source-authored references. Missing rows
        are omitted so the invariant grader reports them as missing evidence.
    """
    observations: dict[str, JSONValue] = {}
    for source, expected_case in oracle.cases.items():
        case_value = raw_cases.get(source, {})
        case = _object(case_value, f"snapshot case {source}")
        declaration_values = case.get("generated_declarations", [])
        declarations = [
            _object(value, f"snapshot {source}.generated_declarations[{index}]")
            for index, value in enumerate(
                _array(declaration_values, f"snapshot {source}.generated_declarations")
            )
        ]
        expected_rows = (
            *expected_case.facts.get("generated_declarations", ()),
            *expected_case.pending_facts.get("generated_declarations", ()),
        )
        for expected in expected_rows:
            match = [
                observed
                for observed in declarations
                if _matches(expected, observed, "generated_declarations")
            ]
            if len(match) != 1:
                continue
            observed = match[0]
            identity_reference = expected.get("identity_reference")
            identity = _semantic_identity_value(observed.get("semantic_identity"))
            if isinstance(identity_reference, str) and identity is not None:
                observations[identity_reference] = identity
            compiler_reference = expected.get("compiler_identity_reference")
            compiler_identity = _semantic_identity_value(
                observed.get("compiler_identity")
            )
            if isinstance(compiler_reference, str) and compiler_identity is not None:
                observations[compiler_reference] = compiler_identity
            target_reference = expected.get("alias_target_identity_reference")
            target_identity = _semantic_identity_value(
                observed.get("alias_target_identity")
            )
            if isinstance(target_reference, str) and target_identity is not None:
                observations[target_reference] = target_identity
    return observations


def _semantic_identity_value(value: JSONValue) -> str | None:
    """Encode one semantic identity tuple without normalizing either field.

    Parameters
    ----------
    value : JSONValue
        Namespace/value object projected from compiler evidence.

    Returns
    -------
    str or None
        Collision-safe identity serialization, or None when no exact identity
        was retained.
    """
    if not isinstance(value, dict):
        return None
    namespace = value.get("namespace")
    identity = value.get("value")
    if not isinstance(namespace, str) or not namespace:
        return None
    if not isinstance(identity, str) or not identity:
        return None
    return json.dumps([namespace, identity], ensure_ascii=False, separators=(",", ":"))


def _grade_cases(
    oracle: OracleDocument, raw_cases: dict[str, JSONValue]
) -> list[GradeFailure]:
    """Grade per-translation-unit persisted facts."""
    failures: list[GradeFailure] = []
    for source, expected_case in oracle.cases.items():
        observed_case_value = raw_cases.get(source, {})
        observed_case = _object(observed_case_value, f"snapshot case {source}")
        case_source_sha = observed_case.get("source_sha256")
        source_sha256 = case_source_sha if isinstance(case_source_sha, str) else None
        for category, expected_rows in expected_case.facts.items():
            if category == "forbidden_artifacts":
                observed_categories = (
                    "declarations",
                    "types",
                    "fields",
                    "callables",
                    "external_owners",
                )
                for expected in expected_rows:
                    actual_rows = [
                        (
                            observed_category,
                            _object(value, f"snapshot {source}.{observed_category}"),
                        )
                        for observed_category in observed_categories
                        for value in _array(
                            observed_case.get(observed_category, []),
                            f"snapshot {source}.{observed_category}",
                        )
                    ]
                    if any(
                        observed.get("name") == expected.get("name")
                        and observed.get("kind") == expected.get("kind")
                        and (
                            observed_category != "external_owners"
                            or expected.get("source") is None
                            or observed.get("source") == expected.get("source")
                        )
                        for observed_category, observed in actual_rows
                    ):
                        failures.append(
                            GradeFailure(
                                source,
                                category,
                                expected,
                                "forbidden artifact is present in persisted output",
                            )
                        )
                continue
            raw_rows = observed_case.get(category, [])
            if not isinstance(raw_rows, list):
                _raise_format_error(f"snapshot {source}.{category}", "must be an array")
            available = [
                _object(row, f"snapshot {source}.{category}[{index}]")
                for index, row in enumerate(raw_rows)
            ]
            for expected in expected_rows:
                match_index = next(
                    (
                        index
                        for index, observed in enumerate(available)
                        if _matches(expected, observed, category, source_sha256)
                    ),
                    None,
                )
                if match_index is None:
                    failures.append(
                        GradeFailure(
                            source,
                            category,
                            expected,
                            "expected fact not persisted exactly",
                        )
                    )
                else:
                    available.pop(match_index)
            for expected in expected_case.pending_facts.get(category, ()):
                match_index = next(
                    (
                        index
                        for index, observed in enumerate(available)
                        if _matches(expected, observed, category, source_sha256)
                    ),
                    None,
                )
                if match_index is None:
                    failures.append(
                        GradeFailure(
                            source,
                            f"pending:{category}",
                            expected,
                            "source-authored assertion remains ungraded in this oracle",
                        )
                    )
                else:
                    available.pop(match_index)
            if category in {
                "callables",
                "calls",
                "enum_members",
                "fields",
                "types",
                "generated_declarations",
            }:
                for unexpected in available:
                    failures.append(
                        GradeFailure(
                            source,
                            category,
                            unexpected,
                            "unexpected persisted source fact or duplicate declaration",
                        )
                    )
    return failures


def _grade_global_metadata(
    oracle: OracleDocument, snapshot: dict[str, JSONValue]
) -> list[GradeFailure]:
    """Grade header ownership and cross-file identity invariants."""
    failures: list[GradeFailure] = []
    observed_headers = snapshot.get("header_context", [])
    if not isinstance(observed_headers, list):
        _raise_format_error("snapshot.header_context", "must be an array")
    header_rows = [
        _object(row, "snapshot.header_context row") for row in observed_headers
    ]
    for expected in oracle.header_context_requests:
        match_index = next(
            (
                index
                for index, observed in enumerate(header_rows)
                if _matches(expected, observed, "header_context")
            ),
            None,
        )
        if match_index is None:
            failures.append(
                GradeFailure(
                    "<headers>",
                    "header_context",
                    expected,
                    "owner profile context differs",
                )
            )
        else:
            header_rows.pop(match_index)
        failures.append(
            GradeFailure(
                "<headers>",
                "pending:header_projection",
                expected,
                "captured owner-TU context is known; header projection is not assessed by this oracle",
            )
        )
    for unexpected in header_rows:
        failures.append(
            GradeFailure(
                "<headers>",
                "header_context",
                unexpected,
                "unexpected owning translation-unit context",
            )
        )
    identity_observations = _object(
        snapshot.get("identity_observations", {}), "snapshot.identity_observations"
    )
    for invariant in oracle.identity_invariants:
        equal_references = invariant.get("equal")
        if equal_references is not None:
            if not isinstance(equal_references, list) or len(equal_references) < 2:
                _raise_format_error(
                    "identity invariant", "equal must contain at least two references"
                )
            reference_names = [
                _string(item, "identity invariant reference")
                for item in equal_references
            ]
            equal_values = [identity_observations.get(item) for item in reference_names]
            if any(not isinstance(value, str) or not value for value in equal_values):
                failures.append(
                    GradeFailure(
                        "<identities>",
                        "identity_invariants",
                        invariant,
                        "equality observation is missing",
                    )
                )
            elif len(set(equal_values)) != 1:
                failures.append(
                    GradeFailure(
                        "<identities>",
                        "identity_invariants",
                        invariant,
                        "equal source entities have different persisted identities",
                    )
                )
            continue
        references = invariant.get("distinct")
        if not isinstance(references, list) or any(
            not isinstance(item, str) for item in references
        ):
            _raise_format_error(
                "identity invariant", "distinct must be an array of references"
            )
        references_list = cast("list[str]", references)
        observed_identities = [
            identity_observations.get(reference) for reference in references_list
        ]
        if any(
            not isinstance(identity, str) or not identity
            for identity in observed_identities
        ):
            failures.append(
                GradeFailure(
                    "<identities>",
                    "identity_invariants",
                    invariant,
                    "identity observation is missing",
                )
            )
        elif len(set(observed_identities)) != len(observed_identities):
            failures.append(
                GradeFailure(
                    "<identities>",
                    "identity_invariants",
                    invariant,
                    "distinct source entities share a persisted identity",
                )
            )
    return failures


def _query_rows(connection: Any, statement: str) -> list[dict[str, Any]]:
    """Read database rows as name-keyed JSON-compatible dictionaries.

    Parameters
    ----------
    connection : object
        Open SQLite or DuckDB DB-API connection.
    statement : str
        Read-only SQL query selecting persisted rows.

    Returns
    -------
    list[dict[str, Any]]
        Rows keyed by the database column names.
    """
    cursor = connection.execute(statement)
    columns = [description[0] for description in cursor.description]
    rows: list[dict[str, Any]] = []
    for raw_row in cursor.fetchall():
        rows.append(
            {str(column): value for column, value in zip(columns, raw_row, strict=True)}
        )
    return rows


def _function_types(
    signature: str, qualified_name: str
) -> tuple[str, list[str], list[str]]:
    """Extract display-level types from a persisted callable signature.

    Parameters
    ----------
    signature : str
        Persisted callable signature.
    qualified_name : str
        Persisted qualified callable identity.

    Returns
    -------
    tuple[str, list[str], list[str]]
        Return type, parameter type spellings, and trailing qualifiers.
    """
    name_start = signature.find(qualified_name)
    if name_start < 0:
        return "", [], []
    open_paren = signature.find("(", name_start + len(qualified_name))
    if open_paren < 0:
        return signature[:name_start].strip(), [], []
    depth = 0
    close_paren = -1
    for index in range(open_paren, len(signature)):
        if signature[index] == "(":
            depth += 1
        elif signature[index] == ")":
            depth -= 1
            if depth == 0:
                close_paren = index
                break
    if close_paren < 0:
        return signature[:name_start].strip(), [], []
    return_type = signature[:name_start].strip()
    raw_parameters = signature[open_paren + 1 : close_paren].strip()
    parameters = (
        []
        if not raw_parameters or raw_parameters == "void"
        else _split_parameters(raw_parameters)
    )
    parameter_types = [
        re.sub(r"\s+[A-Za-z_]\w*$", "", item).strip() for item in parameters
    ]
    qualifiers = signature[close_paren + 1 :].split()
    return return_type, parameter_types, qualifiers


def _split_parameters(value: str) -> list[str]:
    """Split persisted parameter text while respecting nested delimiters.

    Parameters
    ----------
    value : str
        Text between a callable signature's outer parentheses.

    Returns
    -------
    list[str]
        Comma-separated parameter declarations.
    """
    parts: list[str] = []
    start = 0
    depths = {"<": 0, "(": 0, "[": 0}
    pairs = {">": "<", ")": "(", "]": "["}
    for index, character in enumerate(value):
        if character in depths:
            depths[character] += 1
        elif character in pairs:
            depths[pairs[character]] -= 1
        elif character == "," and not any(depths.values()):
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _assert_database_backend_identity(backend: str, database_path: Path) -> None:
    """Require persisted metadata to match the requested structural backend.

    Parameters
    ----------
    backend : str
        Backend label supplied for this database snapshot.
    database_path : pathlib.Path
        Persisted index database path whose adjacent metadata is checked.

    Returns
    -------
    None
        Returns when the database and metadata identify the requested backend.

    Raises
    ------
    OracleFormatError
        If the database is missing, metadata is missing or invalid, or the
        persisted backend name differs from the requested label.
    """
    if backend not in {"sqlite", "duckdb"}:
        _raise_format_error("database backend", "must be sqlite or duckdb")
    if not database_path.is_file():
        _raise_format_error(str(database_path), "database file does not exist")
    metadata_path = database_path.parent / "metadata.json"
    if not metadata_path.is_file():
        _raise_format_error(str(metadata_path), "backend metadata file does not exist")
    try:
        metadata_value = cast("JSONValue", json.loads(metadata_path.read_text()))
    except (OSError, json.JSONDecodeError) as error:
        _raise_format_error(str(metadata_path), f"invalid backend metadata: {error}")
    metadata = _object(metadata_value, str(metadata_path))
    actual_backend = _string(metadata.get("backend_name"), "metadata.backend_name")
    if actual_backend != backend:
        _raise_format_error(
            str(database_path),
            f"requested backend {backend!r} does not match persisted backend "
            f"{actual_backend!r}",
        )


def export_database_snapshot(
    backend: str,
    database_path: Path,
    repository_root: Path,
    oracle: OracleDocument,
    profile_document: Path,
) -> dict[str, JSONValue]:
    """Project persisted SQLite or DuckDB facts into the oracle snapshot form.

    Parameters
    ----------
    backend : str
        Selected persisted backend, either ``sqlite`` or ``duckdb``.
    database_path : pathlib.Path
        Actual backend index database produced by Codira indexing.
    repository_root : pathlib.Path
        Root used to convert persisted absolute file paths to oracle paths.
    oracle : OracleDocument
        Source-authored case and identity references to include in the snapshot.
    profile_document : pathlib.Path
        Combined compiler profiles used to report header owner context.

    Returns
    -------
    dict[str, JSONValue]
        Database-derived snapshot. Missing persisted dimensions remain null or
        absent; no fixture source text is used to fill semantic metadata.
    """
    _assert_database_backend_identity(backend, database_path)
    if backend == "sqlite":
        connection: Any = sqlite3.connect(
            f"file:{database_path.resolve()}?mode=ro", uri=True
        )
    elif backend == "duckdb":
        duckdb_module = importlib.import_module("duckdb")
        connection = duckdb_module.connect(str(database_path), read_only=True)
    else:
        _raise_format_error("database backend", "must be sqlite or duckdb")
    try:
        return _snapshot_from_connection(
            connection,
            backend,
            repository_root.resolve(),
            oracle,
            profile_document,
        )
    finally:
        connection.close()


def _load_database_snapshot_rows(
    connection: Any, repository_root: Path
) -> DatabaseSnapshotRows:
    """Load normalized database tables and index rows by source identity.

    Parameters
    ----------
    connection : object
        Open SQLite or DuckDB DB-API connection.
    repository_root : pathlib.Path
        Indexed source root for exact relative file paths.

    Returns
    -------
    DatabaseSnapshotRows
        Read-only table rows and lookup indexes for snapshot projection.
    """
    files = _query_rows(
        connection,
        "SELECT id, path, hash, analysis_input_fingerprint FROM files",
    )
    file_paths: dict[int, str] = {}
    file_ids_by_path: dict[str, int] = {}
    file_hashes: dict[int, str] = {}
    source_bytes_by_file: dict[int, bytes] = {}
    analysis_input_fingerprints: dict[int, str] = {}
    for row in files:
        file_id = int(row["id"])
        persisted_path = Path(_string(row.get("path"), "files.path"))
        try:
            relative = persisted_path.relative_to(repository_root).as_posix()
        except ValueError as error:
            field = "files.path"
            raise OracleFormatError(field, "is outside repository root") from error
        file_paths[file_id] = relative
        file_ids_by_path[relative] = file_id
        source_hash = _string(row.get("hash"), "files.hash")
        file_hashes[file_id] = source_hash
        fingerprint = row.get("analysis_input_fingerprint")
        if not isinstance(fingerprint, str):
            _raise_format_error("files.analysis_input_fingerprint", "must be text")
        analysis_input_fingerprints[file_id] = fingerprint
        source_path = (repository_root / relative).resolve()
        if not source_path.is_relative_to(repository_root) or not source_path.is_file():
            _raise_format_error(
                relative, "persisted source file is missing or escapes root"
            )
        source_bytes = source_path.read_bytes()
        if hashlib.sha256(source_bytes).hexdigest() != source_hash:
            _raise_format_error(
                relative, "source bytes differ from persisted file hash"
            )
        source_bytes_by_file[file_id] = source_bytes
    symbols = _query_rows(connection, "SELECT * FROM symbol_index")
    symbols_by_id = {str(row["stable_id"]): row for row in symbols}
    symbols_by_file: dict[int, list[dict[str, Any]]] = {}
    callable_identities: dict[tuple[str, str], list[str]] = {}
    for row in symbols:
        file_id = int(row["file_id"])
        symbols_by_file.setdefault(file_id, []).append(row)
        namespace = row.get("semantic_identity_namespace")
        value = row.get("semantic_identity_value")
        if isinstance(namespace, str) and isinstance(value, str):
            callable_identities.setdefault((namespace, value), []).append(
                str(row["stable_id"])
            )
    modules = {
        int(row["id"]): row for row in _query_rows(connection, "SELECT * FROM modules")
    }
    classes = []
    for row in _query_rows(connection, "SELECT * FROM classes"):
        module = modules[int(row["module_id"])]
        classes.append(
            {**row, "file_id": module["file_id"], "module_name": module["name"]}
        )
    provenance_by_stable_id: dict[str, dict[str, object]] = {}
    for provenance_row in _query_rows(
        connection,
        "SELECT file_id, stable_id, payload FROM artifact_provenance",
    ):
        file_id = int(provenance_row["file_id"])
        stable_id = _string(
            provenance_row.get("stable_id"), "artifact_provenance.stable_id"
        )
        payload_text = _string(
            provenance_row.get("payload"), "artifact_provenance.payload"
        )
        try:
            payload = generated_provenance_payload(payload_text)
        except (TypeError, ValueError) as error:
            field = f"artifact_provenance[{stable_id}]"
            raise OracleFormatError(
                field, f"failed core validation: {error}"
            ) from error
        if (
            file_id not in file_hashes
            or payload["source_sha256"] != file_hashes.get(file_id)
            or payload["context_identity"] != analysis_input_fingerprints.get(file_id)
        ):
            _raise_format_error(
                f"artifact_provenance[{stable_id}]",
                "source or outer analysis-input identity does not match its file row",
            )
        if stable_id in provenance_by_stable_id:
            _raise_format_error(
                f"artifact_provenance[{stable_id}]", "stable ID is duplicated"
            )
        provenance_by_stable_id[stable_id] = payload
    return DatabaseSnapshotRows(
        file_paths=file_paths,
        file_ids_by_path=file_ids_by_path,
        file_hashes=file_hashes,
        source_bytes_by_file=source_bytes_by_file,
        analysis_input_fingerprints=analysis_input_fingerprints,
        symbols_by_id=symbols_by_id,
        symbols_by_file=symbols_by_file,
        callable_identities=callable_identities,
        modules=modules,
        classes=classes,
        functions=_query_rows(connection, "SELECT * FROM functions"),
        overloads=_query_rows(connection, "SELECT * FROM overloads"),
        imports=_query_rows(connection, "SELECT * FROM imports"),
        enum_members=_query_rows(connection, "SELECT * FROM enum_members"),
        documentation=_query_rows(connection, "SELECT * FROM documentation_artifacts"),
        edges=_query_rows(connection, "SELECT * FROM call_edges"),
        calls=_query_rows(connection, "SELECT * FROM call_records"),
        provenance_by_stable_id=provenance_by_stable_id,
    )


def _callable_snapshot_rows(
    rows: DatabaseSnapshotRows,
    repository_root: Path,
) -> dict[tuple[int, int, str], dict[str, JSONValue]]:
    """Project persisted definitions and proven V3 aliases.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Normalized database tables and source indexes.
    repository_root : pathlib.Path
        Indexed source root used to normalize compiler receipt coordinates.

    Returns
    -------
    dict[tuple[int, int, str], dict[str, JSONValue]]
        Callable facts keyed by source file, declaration line, and local name.
    """
    callables: dict[tuple[int, int, str], dict[str, JSONValue]] = {}
    for row in rows.functions:
        module = rows.modules[int(row["module_id"])]
        file_id = int(module["file_id"])
        class_id = row.get("class_id")
        owner_name = row.get("owner_name")
        owner_stable_id = row.get("owner_stable_id")
        if not isinstance(owner_name, str) and class_id is not None:
            owner_class = next(
                (item for item in rows.classes if item["id"] == class_id), None
            )
            owner_name = str(owner_class["name"]) if owner_class else None
            if owner_class:
                owner_symbol = next(
                    (
                        item
                        for item in rows.symbols_by_file.get(file_id, [])
                        if item.get("type") == "class"
                        and item.get("name") == owner_class.get("name")
                        and item.get("lineno") == owner_class.get("lineno")
                    ),
                    None,
                )
                if owner_symbol:
                    owner_stable_id = owner_symbol.get("stable_id")
        name = str(row["name"])
        qualified_name = f"{owner_name}::{name}" if owner_name else name
        signature = str(row.get("signature") or "")
        return_type, parameter_types, qualifiers = _function_types(
            signature, qualified_name
        )
        symbol = next(
            (
                item
                for item in rows.symbols_by_file.get(file_id, [])
                if item.get("lineno") == row.get("lineno")
                and item.get("type") in {"function", "method"}
                and (
                    item.get("name") == name
                    or (
                        item.get("owner_name")
                        and str(item.get("name", "")).endswith(f"::{name}")
                    )
                )
            ),
            None,
        )
        stable_id = symbol.get("stable_id") if symbol is not None else None
        provenance = (
            rows.provenance_by_stable_id.get(str(stable_id))
            if isinstance(stable_id, str)
            else None
        )
        is_v3_alias = (
            provenance is not None
            and provenance.get("variant") == "compiler_observed"
            and provenance.get("format_version") == 3
            and provenance.get("role") == "alias"
        )
        if row.get("end_lineno") is None and not is_v3_alias:
            continue
        callables[(file_id, int(row["lineno"]), name)] = {
            "kind": "method" if row.get("is_method") else "function",
            "name": qualified_name,
            "return_type": return_type,
            "parameter_types": cast("JSONValue", parameter_types),
            "qualifiers": cast("JSONValue", qualifiers),
            "returns_value": row.get("end_lineno") is not None
            and return_type != "void",
            "definition_line": int(row["lineno"]),
            "stable_id": symbol.get("stable_id") if symbol else None,
            "owner_name": owner_name,
            "owner_stable_id": owner_stable_id,
            "owner_source": _owner_source(owner_stable_id),
            "linkage": "internal" if row.get("is_public") == 0 else "external",
            "signature": signature,
        }
        callables[(file_id, int(row["lineno"]), name)].update(
            _compiler_observed_callable_fields(rows, file_id, symbol, repository_root)
        )
    return callables


def _compiler_observed_callable_fields(
    rows: DatabaseSnapshotRows,
    file_id: int,
    symbol: dict[str, Any] | None,
    repository_root: Path,
) -> dict[str, JSONValue]:
    """Project v2 compiler observations from the persisted artifact payload.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Strictly validated persisted tables, source bytes and provenance.
    file_id : int
        Source file ID owning the callable.
    symbol : dict[str, Any] or None
        Persisted symbol identity associated with the callable row.
    repository_root : pathlib.Path
        Indexed repository root used to normalize receipt paths.

    Returns
    -------
    dict[str, JSONValue]
        Compiler evidence fields sourced from the persisted v2 payload and
        producer receipt; missing observations remain absent.
    """
    if symbol is None or not isinstance(symbol.get("stable_id"), str):
        return {}
    provenance = rows.provenance_by_stable_id.get(str(symbol["stable_id"]))
    if provenance is None or provenance.get("variant") != "compiler_observed":
        return {}
    fields: dict[str, JSONValue] = {
        "generated": True,
        "source_kind": "compiler_generated",
        "generated_provenance": cast("JSONValue", provenance),
        "source_sha256": rows.file_hashes[file_id],
        "outer_analysis_input_fingerprint": rows.analysis_input_fingerprints[file_id],
    }
    if provenance.get("receipt_namespace") != "clang.frontend.callable-observation.v1":
        return fields
    receipt_text = provenance.get("receipt_json")
    if not isinstance(receipt_text, str):
        _raise_format_error("compiler receipt", "must be a string")
    receipt = _object(cast("JSONValue", json.loads(receipt_text)), "compiler receipt")
    callable_record = _validate_compiler_receipt_identity(receipt, provenance, symbol)
    context = _object(receipt.get("context"), "compiler receipt.context")
    fields["compiler_identity_ref"] = (
        str(symbol["semantic_identity_namespace"])
        + ":"
        + str(symbol["semantic_identity_value"])
    )
    fields["compiler_stdout_sha256"] = cast("str", context["stdout_sha256"])
    macro = receipt.get("macro_expansion")
    if isinstance(macro, dict) and provenance.get("invocation") is not None:
        invocation = cast("dict[str, object]", provenance["invocation"])
        invocation_start, invocation_end = cast("list[int]", invocation["byte_range"])
        invocation_text = cast("str", invocation["text"])
        source = rows.file_paths.get(file_id)
        source_bytes = rows.source_bytes_by_file.get(file_id)
        if source is None or source_bytes is None:
            _raise_format_error("compiler receipt", "source file is unavailable")
        if (
            invocation.get("path") != source
            or macro.get("name") != invocation.get("name")
            or macro.get("invocation") != invocation_text
            or macro.get("byte_range") != [invocation_start, invocation_end]
            or invocation_end > len(source_bytes)
            or source_bytes[invocation_start:invocation_end]
            != invocation_text.encode("utf-8")
        ):
            _raise_format_error(
                "compiler receipt.macro_expansion",
                "does not match the source-authored invocation and bytes",
            )
        fields["generated_invocation_line"] = (
            source_bytes.count(b"\n", 0, invocation_start) + 1
        )
    span_value = callable_record.get("span")
    if not isinstance(span_value, dict):
        return fields
    begin_value = span_value.get("begin")
    if not isinstance(begin_value, dict):
        return fields
    begin = begin_value
    spelling_value = begin.get("spelling")
    if not isinstance(spelling_value, dict):
        return fields
    spelling = spelling_value
    raw_path = spelling.get("path")
    raw_line = spelling.get("line")
    raw_column = spelling.get("column")
    raw_offset = spelling.get("offset")
    try:
        spelling_path = Path(_string(raw_path, "callable.span.begin.spelling.path"))
        if spelling_path.is_absolute():
            spelling_path = spelling_path.resolve().relative_to(
                repository_root.resolve()
            )
        spelling_relative = spelling_path.as_posix()
    except (OSError, ValueError, OracleFormatError):
        return fields
    if (
        spelling_relative == rows.file_paths.get(file_id)
        and isinstance(raw_line, int)
        and not isinstance(raw_line, bool)
        and isinstance(raw_column, int)
        and not isinstance(raw_column, bool)
        and isinstance(raw_offset, int)
        and not isinstance(raw_offset, bool)
    ):
        fields["physical_spelling_location"] = {
            "path": spelling_relative,
            "line": raw_line,
            "column": raw_column,
            "byte_offset": raw_offset,
        }
    return fields


def _validate_compiler_receipt_identity(
    receipt: dict[str, JSONValue],
    provenance: dict[str, object],
    symbol: dict[str, Any],
) -> dict[str, JSONValue]:
    """Validate receipt schema, source context and callable USR.

    Parameters
    ----------
    receipt : dict[str, JSONValue]
        Parsed compiler observation receipt.
    provenance : dict[str, object]
        Core-validated compiler-observed provenance payload.
    symbol : dict[str, Any]
        Persisted symbol row associated with the callable.

    Returns
    -------
    dict[str, JSONValue]
        Validated callable receipt object.
    """
    if receipt.get("schema") != "clang.frontend.callable-observation.v1":
        _raise_format_error("compiler receipt.schema", "is unsupported")
    context = _object(receipt.get("context"), "compiler receipt.context")
    if context.get("analyzer_context_identity") != provenance.get(
        "context_identity"
    ) or context.get("source_sha256") != provenance.get("source_sha256"):
        _raise_format_error(
            "compiler receipt.context",
            "does not match the generated evidence source and analysis identity",
        )
    stdout_sha256 = context.get("stdout_sha256")
    if (
        not isinstance(stdout_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", stdout_sha256) is None
    ):
        _raise_format_error("compiler receipt.context.stdout_sha256", "is invalid")
    callable_record = _object(receipt.get("callable"), "compiler receipt.callable")
    compiler_usr = callable_record.get("usr")
    symbol_namespace = symbol.get("semantic_identity_namespace")
    symbol_value = symbol.get("semantic_identity_value")
    if (
        not isinstance(compiler_usr, str)
        or not compiler_usr
        or symbol_namespace != "clang.usr.v1"
        or symbol_value != compiler_usr
    ):
        _raise_format_error(
            "compiler receipt.callable.usr",
            "does not match the persisted callable semantic identity",
        )
    return callable_record


def _source_artifact_rows(
    rows: DatabaseSnapshotRows,
    callables: dict[tuple[int, int, str], dict[str, JSONValue]],
) -> tuple[
    dict[int, list[dict[str, JSONValue]]],
    dict[int, list[dict[str, JSONValue]]],
    dict[int, list[dict[str, JSONValue]]],
]:
    """Group persisted includes, enum members, and docs by physical file.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Normalized tables and source indexes.
    callables : dict[tuple[int, int, str], dict[str, JSONValue]]
        Projected callable rows used to qualify method documentation owners.

    Returns
    -------
    tuple[dict[int, list[dict[str, JSONValue]]], ...]
        Include rows, enum-member rows, and documentation rows by file ID.
    """
    imports_by_file: dict[int, list[dict[str, JSONValue]]] = {}
    for row in rows.imports:
        module = rows.modules[int(row["module_id"])]
        imports_by_file.setdefault(int(module["file_id"]), []).append(
            {
                "name": row.get("name"),
                "kind": row.get("kind"),
                "line": row.get("lineno"),
            }
        )
    enum_members_by_file: dict[int, list[dict[str, JSONValue]]] = {}
    for row in rows.enum_members:
        enum_members_by_file.setdefault(int(row["file_id"]), []).append(
            {
                "owner": row.get("symbol_name"),
                "name": row.get("name"),
                "ordinal": row.get("ordinal"),
                "line": row.get("lineno"),
            }
        )
    docs_by_file: dict[int, list[dict[str, JSONValue]]] = {}
    callable_facts = list(callables.values())
    for row in rows.documentation:
        owner = rows.symbols_by_id.get(str(row.get("owner_stable_id")))
        owner_name = str(owner.get("name")) if owner else row.get("title")
        if owner and owner.get("type") == "method":
            function = next(
                (
                    item
                    for item in callable_facts
                    if item.get("stable_id") == owner.get("stable_id")
                ),
                None,
            )
            if function:
                owner_name = function["name"]
        docs_by_file.setdefault(int(row["file_id"]), []).append(
            {
                "owner": owner_name,
                "text": str(row.get("text") or "").strip(),
                "line": row.get("lineno"),
            }
        )
    return imports_by_file, enum_members_by_file, docs_by_file


def _call_edge_for_record(
    row: dict[str, Any],
    edges_by_caller: dict[str, list[dict[str, Any]]],
    identities: dict[tuple[str, str], list[str]],
) -> dict[str, Any] | None:
    """Find the persisted edge corresponding to one raw call identity.

    Parameters
    ----------
    row : dict[str, Any]
        Persisted raw call record.
    edges_by_caller : dict[str, list[dict[str, Any]]]
        Persisted call edges grouped by exact caller stable ID.
    identities : dict[tuple[str, str], list[str]]
        Callable stable IDs grouped by exact semantic identity.

    Returns
    -------
    dict[str, Any] or None
        Unique persisted edge for the call, when present.
    """
    caller_id = str(row.get("owner_stable_id") or "")
    target_ns = row.get("target_identity_namespace")
    target_value = row.get("target_identity_value")
    matched_ids = (
        identities.get((str(target_ns), str(target_value)), [])
        if target_ns and target_value
        else []
    )
    for candidate in edges_by_caller.get(caller_id, []):
        if (
            candidate.get("resolved")
            and len(matched_ids) == 1
            and candidate.get("callee_stable_id") == matched_ids[0]
        ):
            return candidate
        if candidate.get("resolved"):
            continue
        try:
            parts = json.loads(str(candidate.get("unresolved_identity")))
        except json.JSONDecodeError:
            parts = []
        if len(parts) >= 6 and parts[4] == target_ns and parts[5] == target_value:
            return candidate
        if (
            row.get("kind") == "unresolved"
            and len(parts) >= 4
            and parts[3] == row.get("target")
        ):
            return candidate
    return None


def _persisted_call_rows(
    rows: DatabaseSnapshotRows,
    callables: dict[tuple[int, int, str], dict[str, JSONValue]],
) -> dict[int, list[dict[str, JSONValue]]]:
    """Project raw calls and persisted exact edges by source file.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Persisted call tables and identity indexes.
    callables : dict[tuple[int, int, str], dict[str, JSONValue]]
        Callable facts used to preserve qualified owner names.

    Returns
    -------
    dict[int, list[dict[str, JSONValue]]]
        Exact call-site rows grouped by the calling source file.
    """
    edges_by_caller: dict[str, list[dict[str, Any]]] = {}
    for db_edge in rows.edges:
        edges_by_caller.setdefault(str(db_edge.get("caller_stable_id")), []).append(
            db_edge
        )
    callables_by_id = {
        str(item.get("stable_id")): item
        for item in callables.values()
        if item.get("stable_id")
    }
    calls_by_file: dict[int, list[dict[str, JSONValue]]] = {}
    for row in rows.calls:
        file_id = int(row["file_id"])
        caller_id = str(row.get("owner_stable_id") or "")
        edge = _call_edge_for_record(row, edges_by_caller, rows.callable_identities)
        caller_symbol = rows.symbols_by_id.get(caller_id)
        caller_fact = callables_by_id.get(caller_id)
        caller_name = (
            str(caller_fact["name"])
            if caller_fact
            else str(caller_symbol.get("name"))
            if caller_symbol
            else str(row.get("owner_name") or "")
        )
        resolved = bool(edge and edge.get("resolved"))
        callee_id = str(edge.get("callee_stable_id")) if resolved and edge else ""
        callee_symbol = rows.symbols_by_id.get(callee_id)
        callee_fact = callables_by_id.get(callee_id)
        target_name = (
            str(callee_fact["name"])
            if callee_fact
            else str(
                (edge or {}).get("external_target_name") or row.get("target") or ""
            )
        )
        calls_by_file.setdefault(file_id, []).append(
            {
                "caller_qualified_name": caller_name,
                "callee_qualified_name": target_name if resolved else None,
                "unresolved_target_qualified_name": None if resolved else target_name,
                "caller_stable_id": caller_id or None,
                "callee_stable_id": edge.get("callee_stable_id")
                if resolved and edge
                else None,
                "callee_definition_line": callee_symbol.get("lineno")
                if callee_symbol
                else None,
                "callee_source": rows.file_paths.get(int(callee_symbol["file_id"]))
                if callee_symbol
                else None,
                "resolved": resolved,
                "resolution_mode": row.get("resolution_mode"),
                "target_identity_namespace": row.get("target_identity_namespace"),
                "target_identity_value": row.get("target_identity_value"),
                "origin": row.get("origin"),
                "line": row.get("lineno"),
                "column": row.get("col_offset"),
                "return_type": callee_fact.get("return_type") if callee_fact else None,
                "parameter_types": callee_fact.get("parameter_types")
                if callee_fact
                else None,
            }
        )
    return calls_by_file


def _case_snapshot_rows(
    projection: ProjectedSnapshotRows, oracle: OracleDocument
) -> dict[str, JSONValue]:
    """Project persisted normalized categories into per-source case rows.

    Parameters
    ----------
    projection : ProjectedSnapshotRows
        Persisted database rows and source indexes grouped by category.
    oracle : OracleDocument
        Source-authored cases to select and group.

    Returns
    -------
    dict[str, JSONValue]
        Case rows keyed by exact oracle-relative source paths.
    """
    rows = projection.database
    cases: dict[str, JSONValue] = {}
    for source in oracle.cases:
        file_id = rows.file_ids_by_path.get(source)
        if file_id is None:
            cases[source] = {"source_sha256": None}
            continue
        source_symbols = rows.symbols_by_file.get(file_id, [])
        declarations: list[dict[str, JSONValue]] = []
        fields: list[dict[str, JSONValue]] = []
        types: list[dict[str, JSONValue]] = []
        source_callables = [
            fact
            for (source_id, _, _), fact in projection.callables.items()
            if source_id == file_id
        ]
        source_classes = [row for row in rows.classes if row.get("file_id") == file_id]
        for class_row in source_classes:
            types.append(
                {
                    "kind": "class",
                    "name": class_row.get("name"),
                    "line": class_row.get("lineno"),
                }
            )
        for symbol in source_symbols:
            kind = str(symbol.get("type"))
            name = str(symbol.get("name"))
            line = symbol.get("lineno")
            if kind in {"function", "method", "module", "class"}:
                continue
            owner = rows.symbols_by_id.get(str(symbol.get("owner_stable_id")))
            if (
                kind == "variable"
                and symbol.get("owner_stable_id")
                and owner
                and owner.get("type") in {"class", "struct"}
            ):
                owner_name = str(symbol.get("owner_name") or "")
                fields.append(
                    {
                        "owner": owner_name,
                        "name": name.removeprefix(f"{owner_name}::")
                        if owner_name
                        else name,
                        "type": symbol.get("type_text"),
                        "line": line,
                        "stable_id": symbol.get("stable_id"),
                        "owner_stable_id": symbol.get("owner_stable_id"),
                        "access": symbol.get("access"),
                    }
                )
            elif kind in {"class", "struct"}:
                if oracle.cases[source].language == "cpp":
                    types.append({"kind": kind, "name": name, "line": line})
                declarations.append({"kind": kind, "name": name, "line": line})
            else:
                declaration: dict[str, JSONValue] = {
                    "kind": kind,
                    "name": name,
                    "line": line,
                }
                if kind == "enum":
                    declaration["enum_members"] = [
                        {key: member.get(key) for key in ("name", "ordinal", "line")}
                        for member in projection.enum_members.get(file_id, [])
                        if member.get("owner") == name
                    ]
                declarations.append(declaration)
        cases[source] = {
            "source_sha256": rows.file_hashes[file_id],
            "includes": cast("JSONValue", projection.includes.get(file_id, [])),
            "declarations": cast("JSONValue", declarations),
            "fields": cast("JSONValue", fields),
            "enum_members": cast("JSONValue", projection.enum_members.get(file_id, [])),
            "types": cast("JSONValue", types),
            "callables": cast("JSONValue", source_callables),
            "documentation": cast(
                "JSONValue", projection.documentation.get(file_id, [])
            ),
            "calls": cast("JSONValue", projection.calls.get(file_id, [])),
            "external_owners": cast(
                "JSONValue",
                [
                    {
                        "kind": "class",
                        "name": fact.get("owner_name"),
                        "source": fact.get("owner_source"),
                        "line": None,
                    }
                    for fact in source_callables
                    if fact.get("owner_stable_id")
                    and fact.get("owner_source") != source
                ],
            ),
            "forbidden_artifacts": [],
            "coverage": [],
            "generated_declarations": cast(
                "JSONValue", _generated_declaration_rows(rows, file_id, source)
            ),
        }
    return cases


def _generated_declaration_rows(
    rows: DatabaseSnapshotRows, file_id: int, source: str
) -> list[dict[str, JSONValue]]:
    """Project V3 callable provenance for definitions, aliases, and prototypes.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Validated persisted database tables and compiler-provenance payloads.
    file_id : int
        Persisted file ID whose generated declarations are requested.
    source : str
        Repository-relative path for the owning physical translation unit.

    Returns
    -------
    list[dict[str, JSONValue]]
        Compiler-observed generated declarations grouped under the source that
        owns each function or overload row.
    """
    function_by_stable_id: dict[str, dict[str, Any]] = {}
    declarations: list[dict[str, JSONValue]] = []
    for function in rows.functions:
        module = rows.modules.get(int(function["module_id"]))
        if module is None or int(module["file_id"]) != file_id:
            continue
        symbol = next(
            (
                item
                for item in rows.symbols_by_file.get(file_id, [])
                if item.get("lineno") == function.get("lineno")
                and item.get("type") in {"function", "method"}
                and (
                    item.get("name") == function.get("name")
                    or str(item.get("name", "")).endswith(f"::{function.get('name')}")
                )
            ),
            None,
        )
        stable_id = str(symbol.get("stable_id") or "") if symbol else ""
        if stable_id:
            function_by_stable_id[stable_id] = function
        declaration = _generated_declaration_row(
            rows,
            GeneratedDeclarationInput(
                stable_id,
                str(function.get("name") or ""),
                int(function["lineno"]),
                source,
                file_id,
                symbol,
            ),
        )
        if declaration is not None:
            declarations.append(declaration)
    for overload in rows.overloads:
        parent_id = str(overload.get("parent_stable_id") or "")
        parent = function_by_stable_id.get(parent_id)
        if parent is None:
            continue
        stable_id = str(overload.get("stable_id") or "")
        declaration = _generated_declaration_row(
            rows,
            GeneratedDeclarationInput(
                stable_id,
                str(parent.get("name") or ""),
                int(overload["lineno"]),
                source,
                file_id,
                rows.symbols_by_id.get(parent_id),
            ),
        )
        if declaration is not None:
            declarations.append(declaration)
    return sorted(
        declarations,
        key=_generated_declaration_sort_key,
    )


def _generated_declaration_row(
    rows: DatabaseSnapshotRows,
    declaration: GeneratedDeclarationInput,
) -> dict[str, JSONValue] | None:
    """Project one validated V2 definition or V3 callable observation.

    Parameters
    ----------
    rows : DatabaseSnapshotRows
        Persisted database tables and provenance.
    declaration : GeneratedDeclarationInput
        Exact persisted identity and source coordinates for the artifact.
    Returns
    -------
    dict[str, JSONValue] or None
        Canonical compiler declaration projection, or None for unrelated
        provenance versions and roles.
    """
    provenance = rows.provenance_by_stable_id.get(declaration.stable_id)
    if provenance is None or provenance.get("variant") != "compiler_observed":
        return None
    version = provenance.get("format_version")
    role = provenance.get("role")
    if version == 2 and role != "definition":
        return None
    if version == 3 and role not in {"definition", "prototype", "alias"}:
        return None
    if version not in {2, 3}:
        return None
    receipt_value = provenance.get("receipt_json")
    if not isinstance(receipt_value, str):
        _raise_format_error(
            declaration.stable_id, "compiler provenance receipt must be text"
        )
    try:
        receipt = _object(
            cast("JSONValue", json.loads(receipt_value)), "compiler receipt"
        )
    except json.JSONDecodeError as error:
        raise OracleFormatError(
            declaration.stable_id, "compiler receipt is invalid JSON"
        ) from error
    callable_value = _object(receipt.get("callable"), "V3 receipt.callable")
    if declaration.symbol is None:
        _raise_format_error(
            declaration.stable_id,
            "generated callable evidence has no persisted symbol identity",
        )
    _validate_compiler_receipt_identity(receipt, provenance, declaration.symbol)
    expected_source_sha = rows.file_hashes.get(declaration.file_id)
    expected_context = rows.analysis_input_fingerprints.get(declaration.file_id)
    if (
        provenance.get("source_sha256") != expected_source_sha
        or provenance.get("context_identity") != expected_context
    ):
        _raise_format_error(
            declaration.stable_id,
            "compiler evidence source digest or context differs from indexed file",
        )
    native_raw = callable_value.get("native_observation")
    if native_raw is None and version == 2:
        native_value: dict[str, JSONValue] = {}
    else:
        native_value = _object(
            native_raw,
            "compiler receipt.callable.native_observation",
        )
    usr = _string(callable_value.get("usr"), "compiler receipt.callable.usr")
    is_definition = callable_value.get("is_definition")
    if role in {"definition", "prototype"} and is_definition is not (
        role == "definition"
    ):
        _raise_format_error(
            declaration.stable_id,
            "compiler receipt callable role differs from persisted provenance role",
        )
    if version == 3:
        _validate_v3_alias_identity(provenance, native_value, declaration.stable_id)
    semantic_identity: dict[str, JSONValue] | None = None
    compiler_identity: dict[str, JSONValue] | None = None
    if role != "prototype":
        namespace = declaration.symbol.get("semantic_identity_namespace")
        value = declaration.symbol.get("semantic_identity_value")
        if isinstance(namespace, str) and isinstance(value, str):
            semantic_identity = {"namespace": namespace, "value": value}
    namespace = declaration.symbol.get("semantic_identity_namespace")
    if isinstance(namespace, str):
        compiler_identity = {"namespace": namespace, "value": usr}
    alias_target_value = provenance.get("alias_target_identity")
    alias_target: JSONValue = (
        cast("JSONValue", alias_target_value)
        if isinstance(alias_target_value, dict)
        else None
    )
    qualified_name = callable_value.get("qualified_name")
    name = qualified_name if isinstance(qualified_name, str) else declaration.name
    return {
        "source": declaration.source,
        "name": name,
        "line": declaration.line,
        "role": cast("JSONValue", role),
        "semantic_identity": cast("JSONValue", semantic_identity),
        "compiler_identity": cast("JSONValue", compiler_identity),
        "linkage_name": native_value.get("linker_symbol"),
        "has_body": native_value.get("has_body"),
        "linker_symbol": native_value.get("linker_symbol"),
        "explicit_linkage_label": native_value.get("explicit_linkage_label"),
        "linkage_label_inherited": native_value.get("linkage_label_inherited"),
        "alias_target_symbol": native_value.get("alias_target_symbol"),
        "alias_target_identity": alias_target,
        "alias_binding_status": native_value.get("alias_binding_status"),
    }


def _validate_v3_alias_identity(
    provenance: dict[str, object],
    native_observation: dict[str, JSONValue],
    stable_id: str,
) -> None:
    """Bind persisted V3 alias identity to the raw compiler target USR.

    Parameters
    ----------
    provenance : dict[str, object]
        Core-validated compiler provenance payload.
    native_observation : dict[str, JSONValue]
        Opaque producer receipt's native callable facts.
    stable_id : str
        Persisted artifact identity used in validation errors.

    Returns
    -------
    None

    Raises
    ------
    OracleFormatError
        If alias target identity and raw compiler target evidence disagree.
    """
    status = native_observation.get("alias_binding_status")
    target_usr = native_observation.get("alias_target_usr")
    target_identity = provenance.get("alias_target_identity")
    if status == "resolved":
        if not isinstance(target_usr, str) or not target_usr:
            _raise_format_error(
                stable_id, "resolved alias receipt lacks its target USR"
            )
        expected_identity = {"namespace": "clang.usr.v1", "value": target_usr}
        if target_identity != expected_identity:
            _raise_format_error(
                stable_id,
                "persisted alias identity differs from the raw compiler target USR",
            )
        return
    if status in {"unresolved", "ambiguous", "not_alias"}:
        if target_usr is not None or target_identity is not None:
            _raise_format_error(
                stable_id,
                "unresolved or non-alias compiler observation retains a target identity",
            )
        return
    if provenance.get("role") == "alias":
        _raise_format_error(
            stable_id, "alias observation has an unknown binding status"
        )


def _generated_declaration_sort_key(
    row: dict[str, JSONValue],
) -> tuple[int, str, str]:
    """Order compiler declarations by persisted location, role, and name.

    Parameters
    ----------
    row : dict[str, JSONValue]
        One normalized compiler declaration snapshot row.

    Returns
    -------
    tuple[int, str, str]
        Deterministic source line, role, and fully qualified name ordering.
    """
    line = row.get("line")
    return (
        line if isinstance(line, int) and not isinstance(line, bool) else 0,
        str(row.get("role") or ""),
        str(row.get("name") or ""),
    )


def _snapshot_from_connection(
    connection: Any,
    backend: str,
    repository_root: Path,
    oracle: OracleDocument,
    profile_document: Path,
) -> dict[str, JSONValue]:
    """Build one case snapshot from normalized persisted tables.

    Parameters
    ----------
    connection : object
        Open backend connection.
    backend : str
        Selected backend name.
    repository_root : pathlib.Path
        Indexed source root.
    oracle : OracleDocument
        Source-authored expected cases and identity references.
    profile_document : pathlib.Path
        Combined compiler profiles for header ownership observations.

    Returns
    -------
    dict[str, JSONValue]
        Persisted row projection grouped by oracle source path.
    """
    rows = _load_database_snapshot_rows(connection, repository_root)
    actual_files = rows.file_ids_by_path
    callable_lookup = _callable_snapshot_rows(rows, repository_root)

    imports_by_file, enum_members_by_file, docs_by_file = _source_artifact_rows(
        rows, callable_lookup
    )

    calls_by_file = _persisted_call_rows(rows, callable_lookup)
    identity_observations = _requested_identity_observations(
        oracle.identity_observation_requests,
        actual_files,
        rows.symbols_by_file,
        rows.calls,
    )
    identity_namespaces = _requested_identity_namespaces(
        oracle.identity_observation_requests,
        actual_files,
        rows.symbols_by_file,
        rows.calls,
    )
    projection = ProjectedSnapshotRows(
        rows,
        callable_lookup,
        imports_by_file,
        enum_members_by_file,
        docs_by_file,
        calls_by_file,
    )
    case_rows = _case_snapshot_rows(projection, oracle)

    return {
        "snapshot_version": 1,
        "backend": backend,
        "cases": case_rows,
        "header_context": cast(
            "JSONValue", _header_context_rows(profile_document, repository_root)
        ),
        "identity_observations": identity_observations,
        "identity_namespace_observations": identity_namespaces,
    }


def _requested_identity_observations(
    requests: tuple[dict[str, JSONValue], ...],
    file_ids_by_path: dict[str, int],
    symbols_by_file: dict[int, list[dict[str, Any]]],
    call_records: list[dict[str, Any]],
) -> dict[str, JSONValue]:
    """Read oracle-requested identities from persisted callable and call rows.

    Parameters
    ----------
    requests : tuple[dict[str, JSONValue], ...]
        Source-authored requests naming exact persisted rows.
    file_ids_by_path : dict[str, int]
        Physical source paths mapped to database file IDs.
    symbols_by_file : dict[int, list[dict[str, Any]]]
        Callable symbol rows grouped by source file.
    call_records : list[dict[str, Any]]
        Persisted raw call records with physical coordinates.

    Returns
    -------
    dict[str, JSONValue]
        Values observed for each source-authored identity reference.
    """
    observations: dict[str, JSONValue] = {}
    for request in requests:
        reference = _string(request.get("reference"), "identity request reference")
        source = _string(request.get("source"), f"{reference}.source")
        identity_field = _string(
            request.get("identity_field"), f"{reference}.identity_field"
        )
        file_id = file_ids_by_path.get(source)
        if file_id is None:
            continue
        kind = _string(request.get("kind"), f"{reference}.kind")
        if kind == "callable":
            name = _string(request.get("name"), f"{reference}.name")
            line_value = request.get("definition_line")
            matches = [
                row
                for row in symbols_by_file.get(file_id, [])
                if row.get("name") == name
                and row.get("type") in {"function", "method"}
                and (line_value is None or row.get("lineno") == line_value)
            ]
        elif kind == "call_target":
            line = request.get("line")
            column = request.get("column")
            matches = [
                row
                for row in call_records
                if row.get("file_id") == file_id
                and row.get("lineno") == line
                and row.get("col_offset") == column
            ]
        else:
            _raise_format_error(f"{reference}.kind", "must be callable or call_target")
        if len(matches) == 1:
            identity = matches[0].get(identity_field)
            if isinstance(identity, str) and identity:
                observations[reference] = identity
    return observations


def _requested_identity_namespaces(
    requests: tuple[dict[str, JSONValue], ...],
    file_ids_by_path: dict[str, int],
    symbols_by_file: dict[int, list[dict[str, Any]]],
    call_records: list[dict[str, Any]],
) -> dict[str, JSONValue]:
    """Read namespace partners for source-requested persisted identities.

    Parameters
    ----------
    requests : tuple[dict[str, JSONValue], ...]
        Source-authored references selecting callable or call target rows.
    file_ids_by_path : dict[str, int]
        Physical source paths mapped to database file IDs.
    symbols_by_file : dict[int, list[dict[str, Any]]]
        Persisted symbols grouped by physical source file.
    call_records : list[dict[str, Any]]
        Persisted call rows with exact target identity namespaces.

    Returns
    -------
    dict[str, JSONValue]
        Identity namespaces keyed by source-authored reference.
    """
    observations: dict[str, JSONValue] = {}
    for request in requests:
        reference = _string(request.get("reference"), "identity request reference")
        source = _string(request.get("source"), f"{reference}.source")
        file_id = file_ids_by_path.get(source)
        if file_id is None:
            continue
        kind = _string(request.get("kind"), f"{reference}.kind")
        if kind == "callable":
            name = _string(request.get("name"), f"{reference}.name")
            line_value = request.get("definition_line")
            matches = [
                row
                for row in symbols_by_file.get(file_id, [])
                if row.get("name") == name
                and row.get("type") in {"function", "method"}
                and (line_value is None or row.get("lineno") == line_value)
            ]
            field_name = "semantic_identity_namespace"
        elif kind == "call_target":
            matches = [
                row
                for row in call_records
                if row.get("file_id") == file_id
                and row.get("lineno") == request.get("line")
                and row.get("col_offset") == request.get("column")
            ]
            field_name = "target_identity_namespace"
        else:
            _raise_format_error(f"{reference}.kind", "must be callable or call_target")
        if len(matches) == 1:
            namespace = matches[0].get(field_name)
            if isinstance(namespace, str) and namespace:
                observations[reference] = namespace
    return observations


def _owner_source(owner_stable_id: JSONValue) -> str | None:
    """Read owner source path from the persisted owner stable ID.

    Parameters
    ----------
    owner_stable_id : JSONValue
        Persisted stable ID for an external class owner.

    Returns
    -------
    str or None
        Repository-relative owner declaration path when encoded.
    """
    if not isinstance(owner_stable_id, str):
        return None
    parts = owner_stable_id.split(":", 3)
    return parts[2] if len(parts) == 4 else None


def _header_context_rows(
    profile_document: Path, repository_root: Path
) -> list[dict[str, JSONValue]]:
    """Derive owner translation units from captured dependency profiles.

    Parameters
    ----------
    profile_document : pathlib.Path
        Combined captured-profile JSON document.
    repository_root : pathlib.Path
        Physical root used to make paths relative.

    Returns
    -------
    list[dict[str, JSONValue]]
        Header dependency paths and their actual owning translation units.
    """
    document = _object(
        json.loads(profile_document.read_text(encoding="utf-8")), "profiles"
    )
    profiles = _array(document.get("profiles"), "profiles.profiles")
    owners: dict[tuple[str, str], set[str]] = {}
    for profile_value in profiles:
        profile = _object(profile_value, "profile")
        source_path = Path(_string(profile.get("source_path"), "profile.source_path"))
        source = source_path.relative_to(repository_root).as_posix()
        language = _string(profile.get("language"), "profile.language")
        dependencies = _array(profile.get("dependencies"), "profile.dependencies")
        for dependency_value in dependencies:
            dependency = _object(dependency_value, "profile dependency")
            dependency_path = Path(_string(dependency.get("path"), "dependency.path"))
            try:
                relative = dependency_path.relative_to(repository_root).as_posix()
            except ValueError:
                continue
            if relative != source:
                owners.setdefault((relative, language), set()).add(source)
    return [
        {
            "path": path,
            "language": language,
            "status": "one_owner_translation_unit"
            if len(source_owners) == 1
            else "multiple_owner_translation_units_hold",
            "owners": cast("JSONValue", sorted(source_owners)),
        }
        for (path, language), source_owners in sorted(owners.items())
    ]


def _export_requested_snapshots(
    specifications: list[str],
    database_root: Path | None,
    profile_document: Path | None,
    oracle: OracleDocument,
    parser: argparse.ArgumentParser,
) -> list[Path]:
    """Export requested backend DBs into immutable JSON snapshot files.

    Parameters
    ----------
    specifications : list[str]
        Backend, database path, and output path triples.
    database_root : pathlib.Path or None
        Root of the indexed source repository.
    profile_document : pathlib.Path or None
        Combined compiler profile document.
    oracle : OracleDocument
        Source-authored oracle used for source-keyed grouping.
    parser : argparse.ArgumentParser
        Command parser used to report invalid combinations.

    Returns
    -------
    list[pathlib.Path]
        Paths to newly exported snapshot JSON files.
    """
    if not specifications:
        return []
    if database_root is None or profile_document is None:
        parser.error(
            "database snapshot export requires --database-root and --profile-document"
        )
    snapshots: list[Path] = []
    for specification in specifications:
        backend, separator, remaining = specification.partition(":")
        database_path_text, separator2, output_path_text = remaining.partition(":")
        if (
            not separator
            or not separator2
            or backend not in {"sqlite", "duckdb"}
            or not database_path_text
            or not output_path_text
        ):
            parser.error("--database-snapshot must be BACKEND:DB_PATH:OUTPUT_PATH")
        snapshot = export_database_snapshot(
            backend,
            Path(database_path_text),
            database_root,
            oracle,
            profile_document,
        )
        output_path = Path(output_path_text)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8") as output:
            json.dump(snapshot, output, indent=2, sort_keys=True)
            output.write("\n")
        snapshots.append(output_path)
    return snapshots


def load_public_constant(specification: str) -> JSONValue:
    """Read one public runtime constant by its explicit module path.

    Parameters
    ----------
    specification : str
        ``module.path:PUBLIC_NAME`` passed by the caller. The value must be a
        JSON scalar so the receipt is deterministic and portable.

    Returns
    -------
    JSONValue
        Public constant value read from the imported runtime module.

    Raises
    ------
    OracleFormatError
        If the requested constant is missing, private, or not a JSON scalar.
    """
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute or attribute.startswith("_"):
        _raise_format_error("public constant", "must be module.path:PUBLIC_NAME")
    module: ModuleType = importlib.import_module(module_name)
    if not hasattr(module, attribute):
        _raise_format_error(specification, "does not exist")
    value: object = getattr(module, attribute)
    if not isinstance(value, (str, int, float, bool)) and value is not None:
        _raise_format_error(specification, "must resolve to a JSON scalar")
    return cast("JSONValue", value)


def capture_freeze(
    files: dict[str, Path], constants: dict[str, JSONValue]
) -> dict[str, JSONValue]:
    """Hash source/profile/helper inputs and record runtime schema constants.

    Parameters
    ----------
    files : dict[str, pathlib.Path]
        Named inputs such as source, module, prepared profile, helper and build
        receipt. Roles are explicit and output paths are resolved.
    constants : dict[str, JSONValue]
        Runtime constants imported from public module attributes.

    Returns
    -------
    dict[str, JSONValue]
        Deterministic versioned freeze receipt.
    """
    file_records: dict[str, JSONValue] = {}
    for role, path in sorted(files.items()):
        resolved = path.resolve(strict=True)
        if not resolved.is_file():
            _raise_format_error(role, "must identify a regular file")
        payload = resolved.read_bytes()
        file_records[role] = {
            "path": str(resolved),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    return {
        "freeze_version": 1,
        "files": file_records,
        "public_constants": dict(sorted(constants.items())),
    }


def audit_freeze(
    expected: dict[str, JSONValue], actual: dict[str, JSONValue]
) -> tuple[FreezeDifference, ...]:
    """Report every changed frozen file record or runtime constant.

    Parameters
    ----------
    expected : dict[str, JSONValue]
        Previously retained immutable receipt.
    actual : dict[str, JSONValue]
        Newly captured receipt using the same role and constant names.

    Returns
    -------
    tuple[FreezeDifference, ...]
        Empty when source, module, profiles, helper, receipt and constants
        match exactly.
    """
    differences: list[FreezeDifference] = []
    if expected.get("freeze_version") != actual.get("freeze_version"):
        differences.append(
            FreezeDifference(
                "freeze_version",
                expected.get("freeze_version"),
                actual.get("freeze_version"),
            )
        )
    for section in ("files", "public_constants"):
        expected_rows = _object(expected.get(section), f"expected.{section}")
        actual_rows = _object(actual.get(section), f"actual.{section}")
        for key in sorted(expected_rows.keys() | actual_rows.keys()):
            old = expected_rows.get(key)
            new = actual_rows.get(key)
            if old != new:
                differences.append(FreezeDifference(f"{section}.{key}", old, new))
    return tuple(differences)


def prepare_profiles(request: ProfilePreparationRequest) -> dict[str, JSONValue]:
    """Prepare profiles for explicitly listed TUs with the shared Clang API.

    Parameters
    ----------
    request : ProfilePreparationRequest
        Explicit source, compile database, helper, and output identities.

    Returns
    -------
    dict[str, JSONValue]
        Profile manifest with source, profile, helper, receipt and schema hashes.
    """
    package: Any = importlib.import_module("codira_clang_frontend")
    create_profile: Any = package.create_frontend_profile
    profile_schema: JSONValue = package.PROFILE_SCHEMA
    request.output_directory.mkdir(parents=True, exist_ok=False)
    rows: list[JSONValue] = []
    for index, source in enumerate(request.sources, start=1):
        absolute_source = source.resolve(strict=True)
        language = "c" if absolute_source.suffix == ".c" else "cpp"
        stem = f"{index:02d}-{absolute_source.stem}"
        attempt_directory = request.output_directory / stem
        profile_path = request.output_directory / f"{stem}.profile.json"
        try:
            frontend, profile = create_profile(
                path=absolute_source,
                root=request.repository_root,
                language=language,
                compile_commands=request.compile_database,
                captured_profiles=None,
                helper_path=request.helper_path,
                build_receipt_path=request.build_receipt_path,
            )
            result, prepared = frontend.prepare_profile(
                profile,
                attempt_dir=attempt_directory,
                profile_output_path=profile_path,
                attempt_id=f"{request.attempt_prefix}-{index:02d}",
            )
            row: dict[str, JSONValue] = {
                "source": str(absolute_source),
                "source_sha256": hashlib.sha256(
                    absolute_source.read_bytes()
                ).hexdigest(),
                "language": language,
                "profile": str(profile_path),
                "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                "profile_schema": profile_schema,
                "dependency_count": len(prepared.dependencies),
                "include_root_count": len(prepared.include_directories),
                "helper_sha256": hashlib.sha256(
                    request.helper_path.read_bytes()
                ).hexdigest(),
                "build_receipt_sha256": hashlib.sha256(
                    request.build_receipt_path.read_bytes()
                ).hexdigest(),
                "frontend_status": result.status,
                "coverage_state": result.coverage_state,
                "dependency_closure_status": (
                    result.dependency_closure.status
                    if result.dependency_closure is not None
                    else None
                ),
                "attempt_directory": str(attempt_directory),
            }
        except Exception as error:  # noqa: BLE001 -- retain every frontend failure receipt
            attempt_directory.mkdir(parents=True, exist_ok=True)
            (attempt_directory / "python.stdout").write_text("", encoding="utf-8")
            (attempt_directory / "python.stderr").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
            (attempt_directory / "python.exit-status").write_text(
                "1\n", encoding="ascii"
            )
            row = {
                "source": str(absolute_source),
                "language": language,
                "status": "failed",
                "exception_type": type(error).__name__,
                "exception": str(error),
                "attempt_directory": str(attempt_directory),
            }
            rows.append(row)
            break
        rows.append(row)
    manifest: dict[str, JSONValue] = {
        "manifest_version": 1,
        "profile_schema": profile_schema,
        "requested_sources": [str(source.resolve()) for source in request.sources],
        "prepared_count": sum(
            1
            for row in rows
            if isinstance(row, dict) and row.get("profile") is not None
        ),
        "attempt_count": len(rows),
        "profiles": rows,
    }
    with (request.output_directory / "profiles-manifest.json").open(
        "x", encoding="utf-8"
    ) as output:
        json.dump(manifest, output, indent=2, sort_keys=True)
        output.write("\n")
    return manifest


def _render_failures(failures: tuple[GradeFailure, ...]) -> list[dict[str, JSONValue]]:
    """Convert grading failures into JSON report rows.

    Parameters
    ----------
    failures : tuple[GradeFailure, ...]
        Failures to serialize.

    Returns
    -------
    list[dict[str, JSONValue]]
        Deterministic report dictionaries.
    """
    return [
        {
            "case": failure.case,
            "category": failure.category,
            "expected": failure.expected,
            "reason": failure.reason,
        }
        for failure in failures
    ]


def main() -> int:
    """Run oracle validation, backend grading, profile capture, or freeze audit.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process status: zero for clean requested operations, one for required
        grading failures, and two for invalid command-line input.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, action="append", default=[])
    parser.add_argument(
        "--database-snapshot",
        action="append",
        default=[],
        metavar="BACKEND:DB_PATH:OUTPUT_PATH",
    )
    parser.add_argument("--database-root", type=Path)
    parser.add_argument("--profile-document", type=Path)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument(
        "--prepare-profile-source", type=Path, action="append", default=[]
    )
    parser.add_argument("--profile-root", type=Path)
    parser.add_argument("--compile-database", type=Path)
    parser.add_argument("--helper", type=Path)
    parser.add_argument("--build-receipt", type=Path)
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--attempt-prefix")
    parser.add_argument(
        "--freeze-file", action="append", default=[], metavar="ROLE=PATH"
    )
    parser.add_argument(
        "--public-constant",
        action="append",
        default=[],
        metavar="ROLE=MODULE:ATTRIBUTE",
    )
    freeze_action = parser.add_mutually_exclusive_group()
    freeze_action.add_argument("--write-freeze", type=Path)
    freeze_action.add_argument("--audit-freeze", type=Path)
    args = parser.parse_args()
    oracle = load_oracle(args.oracle, args.fixture_root)
    selected = set(args.case)
    if selected:
        unknown = selected - oracle.cases.keys()
        if unknown:
            parser.error(f"unknown case(s): {', '.join(sorted(unknown))}")
        oracle = OracleDocument(
            {key: value for key, value in oracle.cases.items() if key in selected},
            oracle.header_context_requests,
            oracle.identity_invariants,
            oracle.identity_observation_requests,
        )
    profile_manifest: dict[str, JSONValue] | None = None
    if args.prepare_profile_source:
        profile_arguments = (
            args.profile_root,
            args.compile_database,
            args.helper,
            args.build_receipt,
            args.profile_output,
            args.attempt_prefix,
        )
        if any(value is None for value in profile_arguments):
            parser.error(
                "profile preparation requires --profile-root, --compile-database, "
                "--helper, --build-receipt, --profile-output, and --attempt-prefix"
            )
        profile_manifest = prepare_profiles(
            ProfilePreparationRequest(
                sources=args.prepare_profile_source,
                repository_root=cast("Path", args.profile_root),
                compile_database=cast("Path", args.compile_database),
                helper_path=cast("Path", args.helper),
                build_receipt_path=cast("Path", args.build_receipt),
                output_directory=cast("Path", args.profile_output),
                attempt_prefix=cast("str", args.attempt_prefix),
            )
        )
    snapshot_paths = [
        *args.snapshot,
        *_export_requested_snapshots(
            args.database_snapshot,
            args.database_root,
            args.profile_document,
            oracle,
            parser,
        ),
    ]
    reports: list[dict[str, JSONValue]] = []
    backends: set[str] = set()
    for snapshot_path in snapshot_paths:
        snapshot = _object(
            json.loads(snapshot_path.read_text(encoding="utf-8")), "snapshot"
        )
        backend = _string(snapshot.get("backend"), "snapshot.backend")
        if backend in backends:
            parser.error(f"duplicate snapshot backend: {backend}")
        backends.add(backend)
        failures = grade_snapshot(oracle, snapshot)
        pending_failures = tuple(
            failure for failure in failures if failure.category.startswith("pending:")
        )
        required_failures = tuple(
            failure
            for failure in failures
            if not failure.category.startswith("pending:")
        )
        reports.append(
            {
                "backend": snapshot["backend"],
                "snapshot": str(snapshot_path),
                "phase_passed": not required_failures,
                "scope_complete": not failures,
                "failure_count": len(required_failures),
                "failures": cast("JSONValue", _render_failures(required_failures)),
                "pending_count": len(pending_failures),
                "pending_assertions": cast(
                    "JSONValue", _render_failures(pending_failures)
                ),
            }
        )
    if snapshot_paths and backends != {"sqlite", "duckdb"}:
        parser.error("grading requires one SQLite and one DuckDB snapshot")
    freeze_report: dict[str, JSONValue] | None = None
    if args.write_freeze or args.audit_freeze:
        files: dict[str, Path] = {}
        constants: dict[str, JSONValue] = {}
        for item in args.freeze_file:
            role, separator, raw_path = item.partition("=")
            if not separator or not role or not raw_path or role in files:
                parser.error(f"invalid or duplicate --freeze-file value: {item}")
            files[role] = Path(raw_path)
        for item in args.public_constant:
            role, separator, specification = item.partition("=")
            if not separator or not role or not specification or role in constants:
                parser.error(f"invalid or duplicate --public-constant value: {item}")
            constants[role] = load_public_constant(specification)
        actual_freeze = capture_freeze(files, constants)
        if args.write_freeze:
            args.write_freeze.parent.mkdir(parents=True, exist_ok=True)
            with args.write_freeze.open("x", encoding="utf-8") as output:
                json.dump(actual_freeze, output, indent=2, sort_keys=True)
                output.write("\n")
            freeze_report = {"written": str(args.write_freeze), "passed": True}
        else:
            expected_freeze = _object(
                json.loads(args.audit_freeze.read_text(encoding="utf-8")),
                "freeze receipt",
            )
            differences = audit_freeze(expected_freeze, actual_freeze)
            freeze_report = {
                "audited": str(args.audit_freeze),
                "passed": not differences,
                "differences": [
                    {
                        "key": difference.key,
                        "expected": difference.expected,
                        "actual": difference.actual,
                    }
                    for difference in differences
                ],
            }
    print(
        json.dumps(
            {
                "oracle_cases": len(oracle.cases),
                "reports": reports,
                "freeze": freeze_report,
                "profile_manifest": profile_manifest,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return int(
        any(
            report.get("phase_passed") is not True
            or report.get("scope_complete") is not True
            for report in reports
        )
        or (freeze_report is not None and freeze_report.get("passed") is not True)
        or (
            profile_manifest is not None
            and profile_manifest.get("prepared_count")
            != profile_manifest.get("attempt_count")
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
