"""Grade Clang pilot records against source facts and independent fixtures.

Parameters
----------
None

Returns
-------
None

Notes
-----
Native frontend completion and semantic completeness are reported separately.
Corpus records without an independent oracle can establish extraction and
coordinate evidence, but never count as semantically verified facts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FactKind = Literal["declaration", "call"]


@dataclass(frozen=True, slots=True)
class ExpectedFact:
    """Describe one manually specified source fact for a fixture.

    Parameters
    ----------
    kind : FactKind
        Whether the fact is a source-written declaration or call.
    name : str
        Expected declared or called name.
    line : int
        One-based source line containing the physical fact.
    column : int
        One-based byte column containing the fact.
    signature : str, optional
        Exact declaration signature when the fact is a declaration.
    function_type : str, optional
        Exact AST function type for prototype and parameter distinctions.
    has_prototype : bool, optional
        Whether a C function declaration includes a prototype.
    is_variadic : bool, optional
        Whether a function type has a variadic parameter list.
    decl_kind : str, optional
        Exact frontend declaration kind, including explicit specializations.
    origin : str, optional
        Required call origin for macro-focused fixtures.
    spelling_line, spelling_column : int, optional
        Expected source-spelling coordinate. For macro replacement calls this
        identifies the macro definition or replacement token.
    expansion_line, expansion_column : int, optional
        Expected expansion coordinate. For calls this identifies the physical
        invocation site in the translation unit.
    """

    kind: FactKind
    name: str
    line: int
    column: int
    signature: str | None = None
    function_type: str | None = None
    has_prototype: bool | None = None
    is_variadic: bool | None = None
    decl_kind: str | None = None
    origin: str | None = None
    spelling_line: int | None = None
    spelling_column: int | None = None
    expansion_line: int | None = None
    expansion_column: int | None = None


@dataclass(frozen=True, slots=True)
class FactIssue:
    """Represent one independently detected mismatch.

    Parameters
    ----------
    category : str
        One of ``invented``, ``missing``, ``duplicate``, or ``origin``.
    fact : str
        Stable compact description of the affected fact.
    """

    category: str
    fact: str


@dataclass(frozen=True, slots=True)
class FixtureGrade:
    """Summarize independent fixture grading without inferring completeness.

    Parameters
    ----------
    expected_count : int
        Number of hand-written expected facts.
    matched_count : int
        Expected facts matched exactly once.
    issues : tuple[FactIssue, ...]
        Missing, invented, duplicate, or incorrectly sourced facts.

    Returns
    -------
    None
    """

    expected_count: int
    matched_count: int
    issues: tuple[FactIssue, ...]

    @property
    def passed(self) -> bool:
        """Return whether every expected fact matched exactly once.

        Parameters
        ----------
        None

        Returns
        -------
        bool
            True when the fixture contains no independent grading issues.
        """

        return not self.issues and self.matched_count == self.expected_count


@dataclass(frozen=True, slots=True)
class RecordGrade:
    """Summarize deterministic checks for one corpus record.

    Parameters
    ----------
    native_acceptance : str
        ``accepted``, ``rejected``, or ``not_established`` from status and
        frontend diagnostics.
    semantic_completeness : str
        ``fixture_verified`` only when an independent fixture oracle exists;
        otherwise ``not_independently_graded``.
    extracted_fact_count : int
        Number of declaration and call rows extracted by the frontend.
    fact_owner_counts : Mapping[str, int]
        Declaration spelling and call expansion owners split into source,
        recorded repository header, and external or unbound paths.
    spelling_owner_counts, expansion_owner_counts : Mapping[str, int]
        Coordinate owner counts for each location channel independently.
    coordinate_checked_count : int
        Number of rows whose source-spelled coordinate points into an input
        source or recorded dependency.
    fully_verified_fact_count : int
        Number of facts matched to hand-written independent expectations.
    major_failure_counts : Mapping[str, int]
        Deterministic counts by status, hold, diagnostic, and unmodeled field.
    issues : tuple[FactIssue, ...]
        Structural and source-coordinate issues detected by this grader.
    """

    native_acceptance: str
    semantic_completeness: str
    extracted_fact_count: int
    fact_owner_counts: Mapping[str, int]
    spelling_owner_counts: Mapping[str, int]
    expansion_owner_counts: Mapping[str, int]
    coordinate_checked_count: int
    fully_verified_fact_count: int
    major_failure_counts: Mapping[str, int]
    issues: tuple[FactIssue, ...]


def grade_fixture_facts(
    record: Mapping[str, object],
    expected: Sequence[ExpectedFact],
) -> FixtureGrade:
    """Compare frontend facts with manually authored fixture expectations.

    Parameters
    ----------
    record : Mapping[str, object]
        One Clang pilot envelope using the pinned translation-unit schema.
    expected : Sequence[ExpectedFact]
        Independent facts written from the fixture source, not generated from
        Clang output.

    Returns
    -------
    FixtureGrade
        Exact-match outcome with missing, invented, duplicate, and origin
        issues retained individually.

    Notes
    -----
    Only declarations classified as ``written`` and calls classified as
    ``source_written`` or the explicitly expected macro origin participate.
    Implicit and template-instantiation declarations remain visible in the
    corpus record but are not mistaken for additional written declarations.
    """

    frontend = _mapping(record.get("frontend"))
    declarations = _sequence(frontend.get("declarations"))
    calls = _sequence(frontend.get("calls"))
    actual: list[tuple[object, ...]] = []

    for declaration in declarations:
        row = _mapping(declaration)
        identity = _mapping(row.get("identity"))
        if identity.get("kind") != "written":
            continue
        location = _mapping(row.get("location"))
        spelling = _coordinate(location.get("spelling"))
        expansion = _coordinate(location.get("expansion"))
        actual.append(
            (
                "declaration",
                _declaration_name(row),
                spelling[0],
                spelling[1],
                None,
                _optional_string(row.get("function_type")),
                row.get("has_prototype")
                if isinstance(row.get("has_prototype"), bool)
                else None,
                row.get("is_variadic")
                if isinstance(row.get("is_variadic"), bool)
                else None,
                _optional_string(row.get("decl_kind")),
                None,
                spelling[0],
                spelling[1],
                expansion[0],
                expansion[1],
            )
        )

    for call in calls:
        row = _mapping(call)
        callee = _mapping(row.get("callee"))
        location = _mapping(row.get("location"))
        spelling = _coordinate(location.get("spelling"))
        expansion = _coordinate(location.get("expansion"))
        actual.append(
            (
                "call",
                _optional_string(callee.get("name")) or "",
                expansion[0],
                expansion[1],
                None,
                None,
                None,
                None,
                None,
                _optional_string(row.get("origin")),
                spelling[0],
                spelling[1],
                expansion[0],
                expansion[1],
            )
        )

    issues: list[FactIssue] = []
    expected_keys = [_expected_key(fact) for fact in expected]
    actual_keys = [_actual_key(fact) for fact in actual]
    expected_counts = Counter(expected_keys)
    actual_counts = Counter(actual_keys)

    for key, count in expected_counts.items():
        if count > 1:
            issues.append(FactIssue("duplicate", f"oracle:{key}"))
        observed = actual_counts.get(key, 0)
        if observed == 0:
            issues.append(FactIssue("missing", f"expected:{key}"))
        elif observed > 1:
            issues.append(FactIssue("duplicate", f"observed:{key}"))

    for key, count in actual_counts.items():
        if key not in expected_counts:
            issues.extend(
                FactIssue("invented", f"observed:{key}") for _ in range(count)
            )

    matched = sum(
        min(expected_counts[key], actual_counts.get(key, 0)) for key in expected_counts
    )
    return FixtureGrade(len(expected), matched, tuple(issues))


def grade_record(
    record: Mapping[str, object],
    source_path: Path,
    expected: Sequence[ExpectedFact] | None = None,
    dependency_paths: Sequence[Path] = (),
    repository_root: Path | None = None,
) -> RecordGrade:
    """Check envelope identity, native status, source coordinates, and facts.

    Parameters
    ----------
    record : Mapping[str, object]
        One Clang pilot envelope.
    source_path : pathlib.Path
        Source file bound by the manifest row.
    expected : Sequence[ExpectedFact] or None, optional
        Independent hand-written fixture facts. Omit for ordinary corpus rows.
    dependency_paths : Sequence[pathlib.Path], optional
        Existing dependency files whose source-spelled coordinates may appear.
    repository_root : pathlib.Path or None, optional
        Checkout root used to distinguish repository headers from external
        dependencies.

    Returns
    -------
    RecordGrade
        Independent status, coordinate, and failure analysis.

    Raises
    ------
    OSError
        If the source or a listed dependency cannot be read.
    """

    source = source_path.read_bytes()
    allowed_sources = {source_path.resolve(): source}
    dependency_files = {path.resolve(): path for path in dependency_paths}
    resolved_dependencies = frozenset(dependency_files)

    frontend = _mapping(record.get("frontend"))
    facts: list[tuple[FactKind, Mapping[str, object]]] = []
    facts.extend(
        ("declaration", _mapping(item))
        for item in _sequence(frontend.get("declarations"))
    )
    facts.extend(("call", _mapping(item)) for item in _sequence(frontend.get("calls")))
    issues: list[FactIssue] = []
    coordinate_checked = 0
    fact_owners: Counter[str] = Counter()
    spelling_owners: Counter[str] = Counter()
    expansion_owners: Counter[str] = Counter()
    for kind, fact in facts:
        location = _mapping(fact.get("location"))
        spelling = _mapping(location.get("spelling"))
        expansion = _mapping(location.get("expansion"))
        identity = _mapping(fact.get("identity"))
        physical_fact = (
            kind == "declaration" and identity.get("kind") == "written"
        ) or (
            kind == "call"
            and fact.get("origin") in {"source_written", "macro_replacement"}
        )
        if not physical_fact:
            fact_owners["unlocated_implicit_or_synthetic"] += 1
            spelling_owners[
                _coordinate_owner(
                    spelling, source_path, resolved_dependencies, repository_root
                )
            ] += 1
            expansion_owners[
                _coordinate_owner(
                    expansion, source_path, resolved_dependencies, repository_root
                )
            ] += 1
            continue

        spelling_owner = _coordinate_owner(
            spelling, source_path, resolved_dependencies, repository_root
        )
        expansion_owner = _coordinate_owner(
            expansion, source_path, resolved_dependencies, repository_root
        )
        spelling_owners[spelling_owner] += 1
        expansion_owners[expansion_owner] += 1
        fact_owners[
            _coordinate_owner(
                spelling if kind == "declaration" else expansion,
                source_path,
                resolved_dependencies,
                repository_root,
            )
        ] += 1
        primary = spelling if kind == "declaration" else expansion
        if not primary or primary.get("path") is None:
            issues.append(FactIssue("coordinate", "missing physical source coordinate"))
            continue

        fact_coordinates_checked = False
        for coordinate in (spelling, expansion):
            path_value = _optional_string(coordinate.get("path"))
            if path_value is None:
                continue
            resolved = Path(path_value).resolve()
            if resolved not in allowed_sources and resolved not in dependency_files:
                # Headers not retained with hash-verified bytes are unbound,
                # not evidence that Clang emitted a bad source coordinate.
                continue
            if resolved not in allowed_sources:
                allowed_sources[resolved] = dependency_files[resolved].read_bytes()
            checked, issue = _check_coordinate(coordinate, allowed_sources)
            fact_coordinates_checked = fact_coordinates_checked or (
                checked
                and resolved
                == Path(_optional_string(primary.get("path")) or "").resolve()
            )
            if issue is not None:
                issues.append(issue)
        coordinate_checked += int(fact_coordinates_checked)

    fixture_grade = (
        grade_fixture_facts(record, expected) if expected is not None else None
    )
    if fixture_grade is not None:
        issues.extend(fixture_grade.issues)

    status = record.get("status")
    diagnostics = _sequence(frontend.get("diagnostics"))
    has_error = any(
        _optional_string(_mapping(item).get("severity"))
        in {"error", "fatal", "fatal error"}
        for item in diagnostics
    )
    if status == "complete" and not has_error:
        native_acceptance = "accepted"
    elif status == "complete" and has_error:
        native_acceptance = "rejected"
    else:
        native_acceptance = "not_established"

    major_failures: Counter[str] = Counter()
    major_failures[f"status:{_optional_string(status) or 'missing'}"] += 1
    for reason in _sequence(record.get("hold_reasons")):
        major_failures[f"hold:{str(reason)}"] += 1
    for diagnostic in diagnostics:
        severity = _optional_string(_mapping(diagnostic).get("severity")) or "unknown"
        major_failures[f"diagnostic:{severity}"] += 1
    for field in _sequence(record.get("unmodeled_fields")):
        major_failures[f"unmodeled:{str(field)}"] += 1

    return RecordGrade(
        native_acceptance=native_acceptance,
        semantic_completeness=(
            "fixture_verified"
            if fixture_grade is not None and fixture_grade.passed
            else "fixture_failed"
            if fixture_grade is not None
            else "not_independently_graded"
        ),
        extracted_fact_count=len(facts),
        fact_owner_counts=dict(sorted(fact_owners.items())),
        spelling_owner_counts=dict(sorted(spelling_owners.items())),
        expansion_owner_counts=dict(sorted(expansion_owners.items())),
        coordinate_checked_count=coordinate_checked,
        fully_verified_fact_count=(fixture_grade.matched_count if fixture_grade else 0),
        major_failure_counts=dict(sorted(major_failures.items())),
        issues=tuple(issues),
    )


def _coordinate_owner(
    coordinate: Mapping[str, object],
    source_path: Path,
    dependency_paths: frozenset[Path],
    repository_root: Path | None,
) -> str:
    """Classify a source coordinate by main file, recorded header, or other.

    Parameters
    ----------
    coordinate : Mapping[str, object]
        Spelling or expansion coordinate from the Clang envelope.
    source_path : pathlib.Path
        Main translation unit source path.
    dependency_paths : Sequence[pathlib.Path]
        Hash-bound repository and external dependencies in the envelope.
    repository_root : pathlib.Path or None
        Repository checkout root when available.

    Returns
    -------
    str
        ``main_file``, ``repository_header``, ``external_or_unbound``, or
        ``missing``.
    """

    path_value = _optional_string(coordinate.get("path"))
    if path_value is None:
        return "missing"
    resolved = Path(path_value).resolve()
    if resolved == source_path.resolve():
        return "main_file"
    if resolved in dependency_paths:
        if repository_root is not None and resolved.is_relative_to(
            repository_root.resolve()
        ):
            return "repository_header"
        return "external_dependency"
    return "external_or_unbound"


def _check_coordinate(
    coordinate: Mapping[str, object],
    allowed_sources: Mapping[Path, bytes],
) -> tuple[bool, FactIssue | None]:
    """Validate one source-spelled coordinate against retained source bytes.

    Parameters
    ----------
    coordinate : Mapping[str, object]
        Coordinate object containing path, line, column, and byte offset.
    allowed_sources : Mapping[pathlib.Path, bytes]
        Resolved source and dependency byte snapshots.

    Returns
    -------
    tuple[bool, FactIssue or None]
        Whether a coordinate was checked and an optional mismatch.
    """

    if not coordinate:
        return False, FactIssue("coordinate", "missing source-spelled coordinate")
    path_value = _optional_string(coordinate.get("path"))
    line = coordinate.get("line")
    column = coordinate.get("column")
    offset = coordinate.get("offset")
    if path_value is None or not all(
        isinstance(value, int) for value in (line, column, offset)
    ):
        return False, FactIssue("coordinate", "malformed source-spelled coordinate")
    resolved = Path(path_value).resolve()
    source = allowed_sources.get(resolved)
    if source is None:
        return False, None
    assert isinstance(line, int) and isinstance(column, int) and isinstance(offset, int)
    if offset < 0 or offset >= len(source):
        return False, FactIssue(
            "coordinate", f"offset outside source:{path_value}:{offset}"
        )
    prefix = source[:offset]
    actual_line = prefix.count(b"\n") + 1
    previous_newline = prefix.rfind(b"\n")
    actual_column = offset - previous_newline
    if (actual_line, actual_column) != (line, column):
        return False, FactIssue(
            "coordinate",
            f"mismatch:{path_value}:{line}:{column}:offset={offset}:actual={actual_line}:{actual_column}",
        )
    return True, None


def _declaration_name(row: Mapping[str, object]) -> str:
    """Return a stable declaration name from the envelope row.

    Parameters
    ----------
    row : Mapping[str, object]
        Declaration record.

    Returns
    -------
    str
        Qualified name, falling back to the unqualified name.
    """

    return (
        _optional_string(row.get("qualified_name"))
        or _optional_string(row.get("name"))
        or ""
    )


def _coordinate(value: object) -> tuple[int | None, int | None]:
    """Read one line and column pair from a coordinate object.

    Parameters
    ----------
    value : object
        Potential coordinate mapping.

    Returns
    -------
    tuple[int or None, int or None]
        One-based line and column, when present.
    """

    coordinate = _mapping(value)
    line = coordinate.get("line")
    column = coordinate.get("column")
    return (
        line if isinstance(line, int) else None,
        column if isinstance(column, int) else None,
    )


def _expected_key(fact: ExpectedFact) -> tuple[object, ...]:
    """Create a deterministic comparison key for an expected fact.

    Parameters
    ----------
    fact : ExpectedFact
        Hand-authored source fact.

    Returns
    -------
    tuple[object, ...]
        Fact fields used for exact matching.
    """

    spelling_line = fact.spelling_line if fact.spelling_line is not None else fact.line
    spelling_column = (
        fact.spelling_column if fact.spelling_column is not None else fact.column
    )
    expansion_line = (
        fact.expansion_line if fact.expansion_line is not None else fact.line
    )
    expansion_column = (
        fact.expansion_column if fact.expansion_column is not None else fact.column
    )
    return (
        fact.kind,
        fact.name,
        fact.line,
        fact.column,
        None,
        fact.function_type,
        fact.has_prototype,
        fact.is_variadic,
        fact.decl_kind,
        fact.origin,
        spelling_line,
        spelling_column,
        expansion_line,
        expansion_column,
    )


def _actual_key(
    fact: tuple[object, ...],
) -> tuple[object, ...]:
    """Return the exact matching key for an extracted fact.

    Parameters
    ----------
    fact : tuple
        Normalized frontend fact.

    Returns
    -------
    tuple[object, ...]
        Fact fields used for exact matching.
    """

    return fact


def _mapping(value: object) -> Mapping[str, object]:
    """Return a safe mapping for untrusted JSON values.

    Parameters
    ----------
    value : object
        Value decoded from JSON.

    Returns
    -------
    Mapping[str, object]
        The input mapping or an empty mapping for another JSON type.
    """

    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    """Return a safe sequence for untrusted JSON arrays.

    Parameters
    ----------
    value : object
        Value decoded from JSON.

    Returns
    -------
    Sequence[object]
        The input list or tuple, or an empty sequence otherwise.
    """

    return value if isinstance(value, (list, tuple)) else ()


def _optional_string(value: object) -> str | None:
    """Return non-empty strings without coercing arbitrary JSON values.

    Parameters
    ----------
    value : object
        Potential string value.

    Returns
    -------
    str or None
        The string if non-empty, otherwise None.
    """

    return value if isinstance(value, str) and value else None
