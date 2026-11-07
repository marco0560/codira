"""Capture independent Clang CLI AST references for a fixed pilot cohort.

The reference lane executes the receipt-bound Clang driver with the pilot's
adapted compile arguments and emits raw Clang JSON AST. It does not consume
facts from the LibTooling helper. Normalized facts are explicitly labeled as
Clang parity and do not establish compiler-independent semantic truth.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

REFERENCE_SCHEMA = "codira.clang-reference-facts/1"
OWNERSHIP_DIAGNOSTICS_SAMPLE_LIMIT = 32
CLANG_JSON_DUMPER_VERSION = "22.1.8"
CLANG_JSON_DUMPER_SOURCE = (
    "https://raw.githubusercontent.com/llvm/llvm-project/"
    "llvmorg-22.1.8/clang/lib/AST/JSONNodeDumper.cpp"
)
CLANG_JSON_DUMPER_SOURCE_LINES = (234, 301)
CLANG_JSON_DUMPER_SOURCE_EXCERPT_SHA256 = (
    "ab51fc921c76d61b9163bdb8d61bb2660101d4dd285707ef51413a327a872731"
)
REQUIRED_CATEGORIES = (
    "native_parse_and_diagnostics",
    "source_owned_declaration_identity",
    "callable_signature_and_prototype",
    "type_and_field_identity",
    "owner_relationships",
    "source_call_sites_and_targets",
    "macro_spelling_and_expansion",
    "template_and_implicit_declarations",
    "header_projection",
    "preprocessor_and_harness_modes",
)
SUPPORTED_CATEGORIES = frozenset(
    {
        "source_owned_declaration_identity",
        "callable_signature_and_prototype",
        "type_and_field_identity",
        "owner_relationships",
        "source_call_sites_and_targets",
    }
)


class ReferenceInputError(ValueError):
    """Signal a profile or source identity validation failure.

    Parameters
    ----------
    message : str
        Description of the invalid input binding.

    Returns
    -------
    None
        Instances carry the message through ``ValueError``.
    """


def _fail(message: str) -> NoReturn:
    """Raise a consistently typed reference-input error.

    Parameters
    ----------
    message : str
        Concrete input identity or safety failure.

    Returns
    -------
    NoReturn
        This function always raises.
    """
    raise ReferenceInputError(message)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, object]:
    """Read a JSON object from a file.

    Parameters
    ----------
    path : pathlib.Path
        JSON file to load.

    Returns
    -------
    dict[str, object]
        Decoded object with string keys.
    """
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{path}: expected a JSON object")
    return value


def _required_string(value: object, context: str) -> str:
    """Require a nonempty string field.

    Parameters
    ----------
    value : object
        Value to validate.
    context : str
        Field description for diagnostics.

    Returns
    -------
    str
        Validated string.
    """
    if not isinstance(value, str) or not value:
        _fail(f"{context}: expected a nonempty string")
    return value


def _object_rows(value: object, context: str) -> list[dict[str, object]]:
    """Validate an array of JSON objects.

    Parameters
    ----------
    value : object
        Candidate array.
    context : str
        Field description for diagnostics.

    Returns
    -------
    list[dict[str, object]]
        Validated object rows.
    """
    if not isinstance(value, list) or any(
        not isinstance(row, dict) or not all(isinstance(key, str) for key in row)
        for row in value
    ):
        _fail(f"{context}: expected an array of objects")
    return value


def _resolve_location_path(raw_path: str, cwd: Path) -> Path:
    """Resolve a Clang AST location path against its compile working directory.

    Parameters
    ----------
    raw_path : str
        Path emitted by the Clang JSON dumper.
    cwd : pathlib.Path
        Working directory used for the exact profile.

    Returns
    -------
    pathlib.Path
        Resolved physical path.
    """
    path = Path(raw_path)
    return (path if path.is_absolute() else cwd / path).resolve()


def _source_line_column(source: bytes, offset: int) -> tuple[int, int]:
    """Map a physical byte offset to one-based line and byte column.

    Parameters
    ----------
    source : bytes
        Original source contents.
    offset : int
        Zero-based byte offset.

    Returns
    -------
    tuple[int, int]
        One-based line and byte column.
    """
    if offset < 0 or offset > len(source):
        _fail(f"source offset {offset} is outside the bound source")
    line = source.count(b"\n", 0, offset) + 1
    previous_newline = source.rfind(b"\n", 0, offset)
    return line, offset - previous_newline


def _walk_with_file_context(
    value: object,
    cwd: Path,
    active_file: list[Path | None] | None = None,
) -> Iterator[tuple[dict[str, object], Path | None, str]]:
    """Walk AST JSON in serialized order and reproduce Clang 22 file context.

    Clang 22.1.8's JSONNodeDumper keeps one global LastLocFilename and omits
    repeated file names. This walk follows serialized location order and
    excludes includedFrom objects, which are emitted through a separate writer
    that does not update that state. The bound implementation is recorded in
    the terminal receipt.

    Parameters
    ----------
    value : object
        JSON AST value.
    cwd : pathlib.Path
        Compile working directory for relative file names.
    active_file : pathlib.Path or None, optional
        Most recent explicit location file.

    Returns
    -------
    collections.abc.Iterator[tuple[dict[str, object], pathlib.Path or None, str]]
        Iterator over location objects, resolved file contexts, and origins.
    """
    if active_file is None:
        active_file = [None]
    if isinstance(value, list):
        for item in value:
            yield from _walk_with_file_context(item, cwd, active_file)
        return
    if not isinstance(value, dict):
        return
    if "offset" in value:
        file_value = value.get("file")
        origin = "explicit"
        if isinstance(file_value, str):
            active_file[0] = _resolve_location_path(file_value, cwd)
        elif active_file[0] is not None:
            origin = "inherited_json_file_context"
        else:
            origin = "unbound"
        yield value, active_file[0], origin
    for key, child in value.items():
        if key in {"includedFrom", "file"}:
            continue
        yield from _walk_with_file_context(child, cwd, active_file)


def _annotate_ast_locations(
    ast: dict[str, object], cwd: Path
) -> tuple[dict[int, tuple[Path | None, str]], Counter[str]]:
    """Build location ownership evidence using the emitted JSON traversal.

    Parameters
    ----------
    ast : dict[str, object]
        Parsed Clang AST root.
    cwd : pathlib.Path
        Exact profile working directory.

    Returns
    -------
    tuple[dict[int, tuple[pathlib.Path or None, str]], collections.Counter[str]]
        Mapping keyed by Python object identity and counts by binding method.
    """
    bindings: dict[int, tuple[Path | None, str]] = {}
    counts: Counter[str] = Counter()
    for location, path, origin in _walk_with_file_context(ast, cwd):
        bindings[id(location)] = (path, origin)
        counts[origin] += 1
    return bindings, counts


def _node_location(
    node: dict[str, object],
    field: str,
    bindings: dict[int, tuple[Path | None, str]],
) -> tuple[dict[str, object] | None, Path | None, str]:
    """Read a node location and its independently tracked file binding.

    Parameters
    ----------
    node : dict[str, object]
        AST node.
    field : str
        Location field, such as ``loc`` or ``range``.
    bindings : dict[int, tuple[pathlib.Path or None, str]]
        Location ownership map.

    Returns
    -------
    tuple[dict[str, object] or None, pathlib.Path or None, str]
        Location, resolved path, and binding method.
    """
    value = node.get("range" if field.startswith("range") else field)
    if field in {"range", "range_end"} and isinstance(value, dict):
        value = value.get("begin" if field == "range" else "end")
    if not isinstance(value, dict):
        return None, None, "missing"
    if "expansionLoc" in value:
        value = value.get("expansionLoc")
    elif "spellingLoc" in value:
        value = value.get("spellingLoc")
    if not isinstance(value, dict):
        return None, None, "missing"
    resolved, origin = bindings.get(id(value), (None, "unbound"))
    return value, resolved, origin


def _proven_lambda_product_owner(
    node: dict[str, object],
    source: bytes,
    source_path: Path,
    bindings: dict[int, tuple[Path | None, str]],
    authored_callable_stack: list[str],
) -> tuple[str, ...] | None:
    """Map a proven lambda wrapper to its unique authored enclosing function.

    Parameters
    ----------
    node : dict[str, object]
        Clang ``LambdaExpr`` node.
    source : bytes
        Bound translation-unit bytes.
    source_path : pathlib.Path
        Exact source path used for this AST.
    bindings : dict[int, tuple[pathlib.Path or None, str]]
        Clang JSON global file-context bindings.
    authored_callable_stack : list[str]
        Source-authored callable definitions enclosing this lambda.

    Returns
    -------
    tuple[str, ...] or None
        The unique source-authored caller chain when the lambda capture
        introducer and implicit record/operator wrapper are all proven.
        Otherwise, ``None`` leaves the product caller owner unresolved.
    """
    if len(authored_callable_stack) != 1:
        return None
    raw_range = node.get("range")
    if not isinstance(raw_range, dict):
        return None
    raw_begin = raw_range.get("begin")
    if not isinstance(raw_begin, dict) or any(
        key in raw_begin for key in ("expansionLoc", "spellingLoc")
    ):
        return None
    lambda_begin, lambda_file, _lambda_origin = _node_location(node, "range", bindings)
    if (
        lambda_begin is None
        or lambda_file != source_path
        or not _source_position_matches(source, lambda_begin)
    ):
        return None
    bracket_offset = lambda_begin.get("offset")
    if (
        not isinstance(bracket_offset, int)
        or source[bracket_offset : bracket_offset + 1] != b"["
    ):
        return None
    children = node.get("inner")
    if not isinstance(children, list):
        return None
    matching_records = sum(
        _is_bound_implicit_lambda_record(child, source_path, bracket_offset, bindings)
        for child in children
        if isinstance(child, dict)
    )
    if matching_records != 1:
        return None
    return tuple(authored_callable_stack)


def _is_bound_implicit_lambda_record(
    node: dict[str, object],
    source_path: Path,
    bracket_offset: int,
    bindings: dict[int, tuple[Path | None, str]],
) -> bool:
    """Check an implicit closure record and its unique implicit call operator.

    Parameters
    ----------
    node : dict[str, object]
        Candidate direct child of a LambdaExpr.
    source_path : pathlib.Path
        Translation-unit path bound to this AST.
    bracket_offset : int
        Proven source byte offset of the lambda capture introducer.
    bindings : dict[int, tuple[pathlib.Path or None, str]]
        Clang JSON global file-context bindings.

    Returns
    -------
    bool
        True when exactly one implicit operator wrapper shares the bracket.
    """
    if node.get("kind") != "CXXRecordDecl" or node.get("isImplicit") is not True:
        return False
    raw_location = node.get("loc")
    if not isinstance(raw_location, dict) or any(
        key in raw_location for key in ("expansionLoc", "spellingLoc")
    ):
        return False
    record_location, record_file, _record_origin = _node_location(node, "loc", bindings)
    if (
        record_location is None
        or record_file != source_path
        or record_location.get("offset") != bracket_offset
    ):
        return False
    children = node.get("inner")
    if not isinstance(children, list):
        return False
    matching_methods = sum(
        _is_bound_implicit_lambda_operator(child, source_path, bracket_offset, bindings)
        for child in children
        if isinstance(child, dict)
    )
    return matching_methods == 1


def _is_bound_implicit_lambda_operator(
    node: dict[str, object],
    source_path: Path,
    bracket_offset: int,
    bindings: dict[int, tuple[Path | None, str]],
) -> bool:
    """Check an implicit lambda operator is located at its capture bracket.

    Parameters
    ----------
    node : dict[str, object]
        Candidate direct child of a closure record.
    source_path : pathlib.Path
        Translation-unit path bound to this AST.
    bracket_offset : int
        Proven source byte offset of the lambda capture introducer.
    bindings : dict[int, tuple[pathlib.Path or None, str]]
        Clang JSON global file-context bindings.

    Returns
    -------
    bool
        True when this is the unique implicit operator() at the bracket.
    """
    if node.get("kind") != "CXXMethodDecl" or node.get("name") != "operator()":
        return False
    # Clang 22 JSON omits isImplicit on the lambda's operator() even though
    # its parent closure record is explicitly implicit. Accept only omission;
    # an explicit false or malformed marker still fails closed.
    if "isImplicit" in node and node["isImplicit"] is not True:
        return False
    raw_location = node.get("loc")
    if not isinstance(raw_location, dict) or any(
        key in raw_location for key in ("expansionLoc", "spellingLoc")
    ):
        return False
    location, physical_file, _origin = _node_location(node, "loc", bindings)
    return (
        location is not None
        and physical_file == source_path
        and location.get("offset") == bracket_offset
    )


def _source_name_match(source: bytes, offset: object, name: object) -> bool:
    """Check an AST declaration name against its physical source bytes.

    Parameters
    ----------
    source : bytes
        Bound main-file source.
    offset : object
        AST byte offset.
    name : object
        AST declaration name.

    Returns
    -------
    bool
        Whether the name occupies a complete, exact source token. Non-ASCII
        bytes and universal-character-name introducers are treated as
        identifier continuations at token boundaries.
    """
    if not isinstance(offset, int) or not isinstance(name, str) or not name:
        return False
    try:
        token = name.encode("utf-8")
    except UnicodeEncodeError:
        return False
    end = offset + len(token)
    if not 0 <= offset <= end <= len(source) or source[offset:end] != token:
        return False
    return not (
        (offset > 0 and _is_identifier_continuation_byte(source[offset - 1]))
        or (end < len(source) and _is_identifier_continuation_byte(source[end]))
    )


def _is_identifier_continuation_byte(value: int) -> bool:
    """Conservatively recognize bytes that can continue a C/C++ identifier.

    Parameters
    ----------
    value : int
        One source byte.

    Returns
    -------
    bool
        True for ASCII identifier bytes, dollar extensions, non-ASCII bytes,
        and a backslash that may begin a universal-character-name escape.
    """
    return (
        48 <= value <= 57
        or 65 <= value <= 90
        or 97 <= value <= 122
        or value in {36, 92, 95}
        or value >= 128
    )


def _source_position_matches(source: bytes, location: dict[str, object]) -> bool:
    """Validate Clang's physical line against the bound source byte offset.

    Parameters
    ----------
    source : bytes
        Original translation-unit bytes.
    location : dict[str, object]
        Clang location with a byte offset and optional line/column.

    Returns
    -------
    bool
        True when the offset is in range and an emitted physical line agrees.
    """
    offset = location.get("offset")
    if not isinstance(offset, int) or not 0 <= offset <= len(source):
        return False
    line, _column = _source_line_column(source, offset)
    ast_line = location.get("line")
    return ast_line is None or ast_line == line


def _declaration_index(ast: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index Clang declaration IDs for resolving member call references.

    Parameters
    ----------
    ast : dict[str, object]
        Parsed Clang AST.

    Returns
    -------
    dict[str, dict[str, object]]
        Process-local declaration IDs mapped to name, kind, and type.
    """
    declarations: dict[str, dict[str, object]] = {}
    pending: list[object] = [ast]
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        identity = value.get("id")
        name = value.get("name")
        if isinstance(identity, str) and isinstance(name, str):
            declarations[identity] = {
                "kind": value.get("kind"),
                "name": name,
                "type": _qualified_type(value.get("type")),
            }
        children = value.get("inner")
        if isinstance(children, list):
            pending.extend(children)
    return declarations


def _new_ownership_diagnostic_groups() -> dict[str, dict[str, object]]:
    """Create ownership classes with exact counters and bounded samples.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, dict[str, object]]
        Mutable diagnostic groups for root, external, and unknown ownership.
    """
    return {
        ownership_class: {"counts_by_reason": Counter(), "samples": []}
        for ownership_class in ("root_intersecting", "proved_external", "unknown")
    }


def normalize_ast(  # noqa: C901 -- category projection shares ownership decisions
    ast: dict[str, object],
    source_path: Path,
    source: bytes,
    working_directory: Path,
) -> dict[str, object]:
    """Normalize only AST facts with explicit physical-file and offset proof.

    Parameters
    ----------
    ast : dict[str, object]
        Parsed Clang JSON AST.
    source_path : pathlib.Path
        Exact translation-unit source path.
    source : bytes
        Source bytes bound by the profile.
    working_directory : pathlib.Path
        Compile command working directory.

    Returns
    -------
    dict[str, object]
        Deterministic source-owned fact lists and explicit ungraded categories.

    Raises
    ------
    TypeError
        If internal ownership diagnostic data has an unexpected shape.
    """
    source_path = source_path.resolve()
    bindings, binding_counts = _annotate_ast_locations(ast, working_directory)
    declarations_by_id = _declaration_index(ast)
    facts: dict[str, list[dict[str, object]]] = {
        "declarations": [],
        "callables": [],
        "types": [],
        "fields": [],
        "calls": [],
        "source_call_sites": [],
        "ungraded_nodes": [],
    }
    owner_stack: list[str] = []
    callable_stack: list[str] = []
    authored_callable_stack: list[str] = []
    lambda_product_owner_stack: list[tuple[str, ...] | None] = []
    ungraded_counts: Counter[str] = Counter()
    ownership_diagnostics: dict[str, object] = {
        "schema_version": 1,
        "sample_limit_per_class": OWNERSHIP_DIAGNOSTICS_SAMPLE_LIMIT,
        "declarations": _new_ownership_diagnostic_groups(),
        "calls": _new_ownership_diagnostic_groups(),
    }
    duplicate_calls: Counter[tuple[object, ...]] = Counter()
    call_facts: dict[tuple[object, ...], dict[str, object]] = {}
    declaration_kinds = {
        "FunctionDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
        "RecordDecl",
        "CXXRecordDecl",
        "ClassTemplateSpecializationDecl",
        "ClassTemplatePartialSpecializationDecl",
        "EnumDecl",
        "TypedefDecl",
        "TypeAliasDecl",
        "NamespaceDecl",
        "FieldDecl",
        "VarDecl",
        "FunctionTemplateDecl",
        "ClassTemplateDecl",
        "TypeAliasTemplateDecl",
    }
    callable_kinds = {
        "FunctionDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
    }
    type_kinds = {
        "RecordDecl",
        "CXXRecordDecl",
        "ClassTemplateSpecializationDecl",
        "ClassTemplatePartialSpecializationDecl",
        "EnumDecl",
        "TypedefDecl",
        "TypeAliasDecl",
        "NamespaceDecl",
    }
    call_kinds = {
        "CallExpr",
        "CXXMemberCallExpr",
        "CXXOperatorCallExpr",
    }

    def record_ownership_diagnostic(
        category: str,
        ownership_class: str,
        reason: str,
        node: dict[str, object],
        locations: list[dict[str, object]],
    ) -> None:
        """Count a rejected AST fact and retain a bounded provenance sample.

        Parameters
        ----------
        category : str
            ``declarations`` or ``calls``.
        ownership_class : str
            ``root_intersecting``, ``proved_external``, or ``unknown``.
        reason : str
            Specific rejection or exclusion reason.
        node : dict[str, object]
            Rejected Clang AST node.
        locations : list[dict[str, object]]
            Relevant source coordinate descriptors.

        Returns
        -------
        None
            The diagnostic counters and bounded sample list are updated.
        """
        groups = ownership_diagnostics[category]
        if not isinstance(groups, dict):
            raise TypeError
        group = groups[ownership_class]
        if not isinstance(group, dict):
            raise TypeError
        counts = group["counts_by_reason"]
        samples = group["samples"]
        if not isinstance(counts, Counter) or not isinstance(samples, list):
            raise TypeError
        counts[reason] += 1
        if len(samples) < OWNERSHIP_DIAGNOSTICS_SAMPLE_LIMIT:
            sample: dict[str, object] = {
                "kind": node.get("kind"),
                "name": node.get("name"),
                "reason": reason,
                "locations": locations,
            }
            if owner_stack:
                sample["owner_chain"] = list(owner_stack)
            if callable_stack:
                sample["caller_chain"] = list(callable_stack)
            samples.append(sample)

    def describe_location(
        location: dict[str, object] | None,
        physical_file: Path | None,
        file_origin: str,
    ) -> dict[str, object]:
        """Return source-coordinate ownership evidence without source text.

        Parameters
        ----------
        location : dict[str, object] or None
            Clang location object, if present.
        physical_file : pathlib.Path or None
            File bound by the versioned global file-context walk.
        file_origin : str
            Binding source, such as explicit, inherited, or unbound.

        Returns
        -------
        dict[str, object]
            Path, byte offset, line, and binding-origin evidence.
        """
        descriptor: dict[str, object] = {
            "path": str(physical_file) if physical_file is not None else None,
            "binding_origin": file_origin,
        }
        if location is not None:
            for key in ("offset", "line"):
                value = location.get(key)
                if isinstance(value, int):
                    descriptor[key] = value
        return descriptor

    def visit(node: object) -> None:  # noqa: C901, PLR0912 -- fact-category projection
        """Visit one AST node in lexical tree order.

        Parameters
        ----------
        node : object
            AST value or child list to visit.

        Returns
        -------
        None
            Facts are accumulated in the enclosing normalization state.
        """
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        name = node.get("name")
        location, physical_file, file_origin = _node_location(node, "loc", bindings)
        parent_owners = tuple(owner_stack)
        source_owned = physical_file == source_path
        offset = location.get("offset") if location else None
        token_matches = _source_name_match(source, offset, name)
        explicit_implicit = node.get("isImplicit") is True
        template_node = (
            "Template" in str(kind) or node.get("isTemplateInstantiation") is True
        )
        if kind in declaration_kinds:
            declaration_descriptor = describe_location(
                location, physical_file, file_origin
            )
            if explicit_implicit:
                ownership_class = (
                    "root_intersecting"
                    if source_owned
                    else "proved_external"
                    if physical_file is not None
                    else "unknown"
                )
                record_ownership_diagnostic(
                    "declarations",
                    ownership_class,
                    "implicit_declaration",
                    node,
                    [declaration_descriptor],
                )
                if source_owned or physical_file is None:
                    ungraded_counts["implicit_declaration"] += 1
            elif template_node:
                ownership_class = (
                    "root_intersecting"
                    if source_owned
                    else "proved_external"
                    if physical_file is not None
                    else "unknown"
                )
                record_ownership_diagnostic(
                    "declarations",
                    ownership_class,
                    "template_declaration",
                    node,
                    [declaration_descriptor],
                )
                if source_owned or physical_file is None:
                    ungraded_counts["template_declaration"] += 1
            elif (
                source_owned
                and token_matches
                and isinstance(location, dict)
                and isinstance(offset, int)
                and _source_position_matches(source, location)
            ):
                line, column = _source_line_column(source, offset)
                fact = {
                    "kind": kind,
                    "name": name,
                    "offset": offset,
                    "line": line,
                    "column": column,
                    "owner_chain": list(parent_owners),
                    "qualified_name": "::".join((*parent_owners, str(name))),
                    "file_binding": file_origin,
                    "type": _qualified_type(node.get("type")),
                    "is_definition": _has_definition_body(node),
                }
                facts["declarations"].append(fact)
                if kind in callable_kinds:
                    facts["callables"].append(fact)
                elif kind in type_kinds:
                    facts["types"].append(fact)
                elif kind == "FieldDecl":
                    facts["fields"].append(fact)
            else:
                ownership_class = (
                    "root_intersecting"
                    if source_owned
                    else "proved_external"
                    if physical_file is not None
                    else "unknown"
                )
                if physical_file is not None and not source_owned:
                    diagnostic_reason = "outside_translation_unit"
                elif location is None:
                    diagnostic_reason = "location_missing"
                elif physical_file is None:
                    diagnostic_reason = "file_context_unknown"
                elif not isinstance(offset, int):
                    diagnostic_reason = "offset_missing"
                elif not _source_position_matches(source, location):
                    diagnostic_reason = "source_line_or_offset_invalid"
                elif not token_matches:
                    diagnostic_reason = "source_name_token_mismatch"
                else:
                    diagnostic_reason = "source_ownership_unproven"
                record_ownership_diagnostic(
                    "declarations",
                    ownership_class,
                    diagnostic_reason,
                    node,
                    [declaration_descriptor],
                )
                if source_owned or physical_file is None:
                    ungraded_counts["declaration_location_or_name_unproven"] += 1
                    facts["ungraded_nodes"].append(
                        {
                            "kind": kind,
                            "name": name,
                            "offset": offset,
                            "reason": "physical ownership or source token not proven",
                        }
                    )
        if kind in call_kinds:
            begin, begin_file, begin_origin = _node_location(node, "range", bindings)
            end_loc, end_file, end_origin = _node_location(node, "range_end", bindings)
            call_locations = [
                describe_location(begin, begin_file, begin_origin),
                describe_location(end_loc, end_file, end_origin),
            ]
            if (
                begin_file == source_path
                and end_file == source_path
                and begin
                and end_loc
                and _source_position_matches(source, begin)
                and _source_position_matches(source, end_loc)
            ):
                begin_offset = begin.get("offset")
                end_offset = end_loc.get("offset")
                end_tok_len = end_loc.get("tokLen", 1)
                if (
                    isinstance(begin_offset, int)
                    and isinstance(end_offset, int)
                    and isinstance(end_tok_len, int)
                    and 0 <= begin_offset <= end_offset < len(source)
                    and end_offset + end_tok_len <= len(source)
                ):
                    direct_target = _direct_callee(node, declarations_by_id)
                    if lambda_product_owner_stack:
                        proven_owners = [
                            owner
                            for owner in lambda_product_owner_stack
                            if owner is not None
                        ]
                        if (
                            len(proven_owners) == len(lambda_product_owner_stack)
                            and len(set(proven_owners)) == 1
                        ):
                            product_caller_chain: list[str] | None = list(
                                proven_owners[0]
                            )
                            product_owner_mapping_status = (
                                "proven_enclosing_authored_callable"
                            )
                        else:
                            product_caller_chain = None
                            product_owner_mapping_status = (
                                "lambda_product_owner_unproven"
                            )
                            ungraded_counts["lambda_product_owner_unproven"] += 1
                    else:
                        product_caller_chain = list(callable_stack)
                        product_owner_mapping_status = "same_as_compiler_callable_chain"
                    fact = {
                        "kind": kind,
                        "begin_offset": begin_offset,
                        "end_offset": end_offset,
                        "end_token_length": end_tok_len,
                        "line": _source_line_column(source, begin_offset)[0],
                        "owner_chain": list(parent_owners),
                        "caller_chain": list(callable_stack),
                        "product_caller_chain": product_caller_chain,
                        "product_owner_mapping_status": product_owner_mapping_status,
                        "file_binding": [begin_origin, end_origin],
                        "source_span_sha256": hashlib.sha256(
                            source[begin_offset : end_offset + end_tok_len]
                        ).hexdigest(),
                        "direct_target": direct_target,
                        "target_state": (
                            "resolved_in_ast"
                            if direct_target is not None
                            else "unresolved_or_ambiguous"
                        ),
                    }
                    key = (
                        kind,
                        begin_offset,
                        end_offset,
                        json.dumps(direct_target, sort_keys=True),
                        tuple(callable_stack),
                    )
                    duplicate_calls[key] += 1
                    call_facts.setdefault(key, fact)
                else:
                    ungraded_counts["call_range_offset_missing"] += 1
                    record_ownership_diagnostic(
                        "calls",
                        "root_intersecting",
                        "invalid_offset_range",
                        node,
                        call_locations,
                    )
            else:
                endpoint_files = (begin_file, end_file)
                if source_path in endpoint_files:
                    ownership_class = "root_intersecting"
                elif all(path is not None for path in endpoint_files):
                    ownership_class = "proved_external"
                else:
                    ownership_class = "unknown"
                if ownership_class == "proved_external":
                    reason = "outside_translation_unit"
                elif begin is None:
                    reason = "begin_location_missing"
                elif end_loc is None:
                    reason = "end_location_missing"
                elif begin_file is None or end_file is None:
                    reason = "file_context_unknown"
                elif begin_file != end_file:
                    reason = "cross_file_range"
                elif not _source_position_matches(source, begin) or not (
                    _source_position_matches(source, end_loc)
                ):
                    reason = "source_line_or_offset_invalid"
                else:
                    reason = "source_range_not_owned"
                record_ownership_diagnostic(
                    "calls", ownership_class, reason, node, call_locations
                )
                if source_path in endpoint_files or None in endpoint_files:
                    ungraded_counts["call_physical_ownership_unproven"] += 1
        named_owner = (
            isinstance(name, str)
            and bool(name)
            and kind
            in {
                "NamespaceDecl",
                "RecordDecl",
                "CXXRecordDecl",
                "ClassTemplateSpecializationDecl",
            }
        )
        if named_owner:
            owner_stack.append(cast("str", name))
        named_callable = kind in callable_kinds and isinstance(name, str) and bool(name)
        if named_callable:
            callable_stack.append(cast("str", name))
        authored_callable = (
            named_callable
            and not explicit_implicit
            and source_owned
            and token_matches
            and isinstance(location, dict)
            and _source_position_matches(source, location)
            and _has_definition_body(node)
        )
        if authored_callable:
            authored_callable_stack.append(cast("str", name))
        is_lambda_expr = kind == "LambdaExpr"
        if is_lambda_expr:
            lambda_product_owner_stack.append(
                _proven_lambda_product_owner(
                    node,
                    source,
                    source_path,
                    bindings,
                    authored_callable_stack,
                )
            )
        children = node.get("inner")
        if isinstance(children, list):
            visit(children)
        if is_lambda_expr:
            lambda_product_owner_stack.pop()
        if authored_callable:
            authored_callable_stack.pop()
        if named_owner:
            owner_stack.pop()
        if named_callable:
            callable_stack.pop()

    visit(ast)
    for key, count in duplicate_calls.items():
        fact = call_facts[key]
        fact["ast_occurrence_count"] = count
        fact["status"] = (
            "duplicate_ast_occurrences_ungraded"
            if count > 1
            else "unique_ast_occurrence"
        )
        if count > 1:
            ungraded_counts["duplicate_call_ast_occurrences"] += count - 1
        if fact["direct_target"] is None:
            ungraded_counts["call_target_unresolved_or_ambiguous"] += 1
        facts["calls"].append(fact)
    call_sites: dict[tuple[int, int, int], list[dict[str, object]]] = {}
    for fact in facts["calls"]:
        begin_offset = fact.get("begin_offset")
        end_offset = fact.get("end_offset")
        end_token_length = fact.get("end_token_length")
        if (
            isinstance(begin_offset, int)
            and isinstance(end_offset, int)
            and isinstance(end_token_length, int)
        ):
            key = (begin_offset, end_offset, end_token_length)
            call_sites.setdefault(key, []).append(fact)
    for (begin_offset, end_offset, end_token_length), candidates in call_sites.items():
        ast_occurrence_count = 0
        for candidate in candidates:
            occurrence_count = candidate.get("ast_occurrence_count", 1)
            ast_occurrence_count += (
                occurrence_count if isinstance(occurrence_count, int) else 1
            )
        caller_contexts = sorted(
            {
                tuple(caller_chain)
                for candidate in candidates
                if isinstance((caller_chain := candidate.get("caller_chain")), list)
                and all(isinstance(name, str) for name in caller_chain)
            }
        )
        unique_candidate = (
            candidates[0]
            if ast_occurrence_count == 1
            and len(candidates) == 1
            and len(caller_contexts) == 1
            else None
        )
        ordered_candidates = sorted(
            candidates,
            key=lambda candidate: json.dumps(candidate, sort_keys=True),
        )
        if len(caller_contexts) > 1:
            status = "multiple_caller_contexts_at_source_span_ungraded"
            ungraded_counts["multiple_caller_contexts_at_source_span"] += (
                ast_occurrence_count
            )
        elif unique_candidate is not None:
            status = "unique_source_call_site"
        else:
            status = "multiple_ast_nodes_at_source_span_ungraded"
        source_call_site = {
            "begin_offset": begin_offset,
            "end_offset": end_offset,
            "end_token_length": end_token_length,
            "line": candidates[0]["line"],
            "caller_contexts": [list(context) for context in caller_contexts],
            "source_span_sha256": candidates[0]["source_span_sha256"],
            "candidate_ast_kinds": sorted(
                {str(candidate["kind"]) for candidate in candidates}
            ),
            "ast_candidate_count": len(candidates),
            "ast_occurrence_count": ast_occurrence_count,
            "candidates": [dict(candidate) for candidate in ordered_candidates],
            "direct_target": (
                unique_candidate["direct_target"] if unique_candidate else None
            ),
            "status": status,
        }
        if source_call_site["status"] != "unique_source_call_site":
            ungraded_counts["multiple_ast_nodes_at_source_call_site"] += (
                ast_occurrence_count
            )
        facts["source_call_sites"].append(source_call_site)
    for values in facts.values():
        values.sort(key=_fact_sort_key)
    serialized_ownership_diagnostics: dict[str, object] = {
        "schema_version": ownership_diagnostics["schema_version"],
        "sample_limit_per_class": ownership_diagnostics["sample_limit_per_class"],
    }
    for category in ("declarations", "calls"):
        category_groups = ownership_diagnostics[category]
        if not isinstance(category_groups, dict):
            raise TypeError
        serialized_groups: dict[str, object] = {}
        for ownership_class, group in category_groups.items():
            if not isinstance(group, dict):
                raise TypeError
            counts = group["counts_by_reason"]
            samples = group["samples"]
            if not isinstance(counts, Counter) or not isinstance(samples, list):
                raise TypeError
            serialized_groups[ownership_class] = {
                "counts_by_reason": dict(sorted(counts.items())),
                "samples": samples,
            }
        serialized_ownership_diagnostics[category] = serialized_groups
    return {
        "source_path": str(source_path),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "file_binding_counts": dict(sorted(binding_counts.items())),
        "facts": facts,
        "ungraded_counts": dict(sorted(ungraded_counts.items())),
        "ownership_diagnostics": serialized_ownership_diagnostics,
        "required_category_coverage": {
            category: {
                "status": "partially_graded"
                if category in SUPPORTED_CATEGORIES
                else "ungraded",
                "reason": (
                    "normalized only where source-file ownership and byte offsets are proven using the bound Clang JSON dumper's global file-context rules"
                    if category in SUPPORTED_CATEGORIES
                    else "reference extractor does not establish this category for full-file parity"
                ),
            }
            for category in REQUIRED_CATEGORIES
        },
        "whole_file_parity": False,
        "interpretation": "clang_parity_only_same_compiler_not_compiler_independent_truth",
    }


def _fact_sort_key(row: dict[str, object]) -> tuple[str, int, str]:
    """Build a deterministic ordering key for a normalized fact.

    Parameters
    ----------
    row : dict[str, object]
        Normalized AST fact.

    Returns
    -------
    tuple[str, int, str]
        Fact kind, source offset, and name.
    """
    offset = row.get("offset", row.get("begin_offset"))
    if not isinstance(offset, int):
        offset = -1
    return (
        str(row.get("kind", "")),
        offset,
        str(row.get("name", "")),
    )


def _qualified_type(value: object) -> str | None:
    """Extract a Clang display type without claiming canonical type identity.

    Parameters
    ----------
    value : object
        AST ``type`` field.

    Returns
    -------
    str or None
        Clang's ``qualType`` display when present.
    """
    if not isinstance(value, dict):
        return None
    text = value.get("qualType")
    return text if isinstance(text, str) else None


def _has_definition_body(node: dict[str, object]) -> bool:
    """Check whether an AST declaration has a recognized body child.

    Parameters
    ----------
    node : dict[str, object]
        Declaration node.

    Returns
    -------
    bool
        True when the node has a compound or function-try body child.
    """
    children = node.get("inner")
    return isinstance(children, list) and any(
        isinstance(child, dict) and child.get("kind") in {"CompoundStmt", "CXXTryStmt"}
        for child in children
    )


def _direct_callee(
    node: dict[str, object], declarations: dict[str, dict[str, object]]
) -> dict[str, object] | None:
    """Find a directly referenced callee identity in supported call nodes.

    Parameters
    ----------
    node : dict[str, object]
        Clang call expression.
    declarations : dict[str, dict[str, object]]
        Declaration index for this exact AST process.

    Returns
    -------
    dict[str, object] or None
        Direct declaration name/kind/type when unambiguous.
    """
    direct_declaration_kinds = {
        "FunctionDecl",
        "FunctionTemplateDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
    }
    transparent_wrappers = {
        "ConstantExpr",
        "ExprWithCleanups",
        "ImplicitCastExpr",
        "ParenExpr",
        "MaterializeTemporaryExpr",
    }
    children = node.get("inner")
    if not isinstance(children, list) or not children:
        return None
    current = children[0]
    while isinstance(current, dict):
        kind = current.get("kind")
        if kind == "DeclRefExpr":
            referenced = current.get("referencedDecl")
            if (
                isinstance(referenced, dict)
                and referenced.get("kind") in direct_declaration_kinds
                and isinstance(referenced.get("name"), str)
            ):
                return {
                    "kind": referenced.get("kind"),
                    "name": referenced.get("name"),
                    "type": _qualified_type(referenced.get("type")),
                }
            return None
        if kind == "MemberExpr":
            member = current.get("referencedMemberDecl")
            if not isinstance(member, str):
                return None
            referenced_member = declarations.get(member)
            if (
                referenced_member is not None
                and referenced_member.get("kind") in direct_declaration_kinds
            ):
                return referenced_member
            return None
        if kind not in transparent_wrappers:
            return None
        nested = current.get("inner")
        if not isinstance(nested, list) or len(nested) != 1:
            return None
        current = nested[0]
    return None


def _load_profile_inputs(  # noqa: C901, PLR0912 -- prelaunch identity gates
    selection_id: str,
    cohort_manifest_path: Path,
    profile_manifest_root: Path,
    preflight_path: Path,
    build_receipt_path: Path,
) -> dict[str, object]:
    """Validate and bind one cohort row to its prepared Clang profile.

    Parameters
    ----------
    selection_id : str
        Exact cohort row ID.
    cohort_manifest_path : pathlib.Path
        Immutable cohort manifest.
    profile_manifest_root : pathlib.Path
        Directory containing per-selection profile manifests.
    preflight_path : pathlib.Path
        Passed profile API preflight with compiler and adapted argv receipts.
    build_receipt_path : pathlib.Path
        Immutable Clang helper build receipt binding compiler/resource identity.

    Returns
    -------
    dict[str, object]
        Source, profile, adapted argv, compiler, dependencies, and hashes.
    """
    cohort = _read_object(cohort_manifest_path)
    cohort_rows = _object_rows(cohort.get("rows"), "cohort.rows")
    row_matches = [
        row for row in cohort_rows if row.get("selection_id") == selection_id
    ]
    if len(row_matches) != 1:
        _fail(f"{selection_id}: expected exactly one cohort row")
    cohort_row = row_matches[0]
    preflight = _read_object(preflight_path)
    preflight_rows = _object_rows(
        preflight.get("selected_profiles_and_exact_adaptations"), "preflight selections"
    )
    selected = [
        row for row in preflight_rows if row.get("selection_id") == selection_id
    ]
    if len(selected) != 1:
        _fail(f"{selection_id}: expected exactly one preflight profile row")
    selected_row = selected[0]
    profile_manifest_path = (
        profile_manifest_root / selection_id / "profiles-manifest.json"
    )
    profile_manifest = _read_object(profile_manifest_path)
    profile_entries = _object_rows(
        profile_manifest.get("profiles"), "profile manifest entries"
    )
    if len(profile_entries) != 1:
        _fail(f"{selection_id}: expected one prepared profile")
    profile_entry = profile_entries[0]
    profile_path = Path(_required_string(profile_entry.get("profile"), "profile path"))
    profile_digest = _sha256(profile_path)
    if profile_digest != profile_entry.get("profile_sha256"):
        _fail(f"{selection_id}: prepared profile hash mismatch")
    profile = _read_object(profile_path)
    profile_rows = _object_rows(profile.get("profiles"), "profile.profiles")
    if len(profile_rows) != 1:
        _fail(f"{selection_id}: prepared profile must contain one profile row")
    profile_row = profile_rows[0]
    original_argv = profile_row.get("argv")
    if (
        not isinstance(original_argv, list)
        or not original_argv
        or not all(isinstance(arg, str) for arg in original_argv)
    ):
        _fail(f"{selection_id}: original profile argv is invalid")
    adapted_argv = selected_row.get("adapted_clang_argv")
    if not isinstance(adapted_argv, list) or not all(
        isinstance(arg, str) for arg in adapted_argv
    ):
        _fail(f"{selection_id}: adapted Clang argv is invalid")
    if "-fsyntax-only" not in adapted_argv:
        _fail(f"{selection_id}: adapted argv lacks -fsyntax-only")
    forbidden = {"-c", "-S", "-E", "-o", "-MF", "-serialize-diagnostics"}
    if any(argument in forbidden for argument in adapted_argv):
        _fail(f"{selection_id}: adapted argv contains a build or file-output action")
    if any("ast-dump" in argument for argument in adapted_argv):
        _fail(f"{selection_id}: profile already contains AST-dump instrumentation")
    source_path = Path(
        _required_string(selected_row.get("source"), "preflight source")
    ).resolve()
    source = source_path.read_bytes()
    source_digest = hashlib.sha256(source).hexdigest()
    if source_digest != selected_row.get(
        "source_sha256"
    ) or source_digest != profile_entry.get("source_sha256"):
        _fail(f"{selection_id}: source digest mismatch")
    if str(source_path) != cohort_row.get("source_path"):
        _fail(f"{selection_id}: source path differs from cohort manifest")
    if profile_row.get("argv") != selected_row.get("original_argv"):
        _fail(f"{selection_id}: preflight original argv differs from prepared profile")
    if (
        Path(original_argv[0]).name
        != Path(
            _required_string(
                selected_row.get("original_driver"), "original driver label"
            )
        ).name
    ):
        _fail(f"{selection_id}: original driver identity mismatch")
    dependencies = _object_rows(profile_row.get("dependencies"), "profile dependencies")
    dependency_failures: list[str] = []
    for dependency in dependencies:
        path = Path(_required_string(dependency.get("path"), "dependency path"))
        expected = _required_string(dependency.get("sha256"), "dependency digest")
        if not path.is_file() or _sha256(path) != expected:
            dependency_failures.append(str(path))
    if dependency_failures:
        _fail(
            f"{selection_id}: profile dependencies changed: {dependency_failures[:5]}"
        )
    receipt = _read_object(build_receipt_path)
    receipt_digest = _sha256(build_receipt_path)
    binding = preflight.get("correct_helper_binding")
    if (
        not isinstance(binding, dict)
        or binding.get("build_receipt_sha256") != receipt_digest
    ):
        _fail(f"{selection_id}: preflight/build receipt digest mismatch")
    compiler = Path(
        _required_string(receipt.get("compiler_path"), "receipt compiler path")
    )
    compiler_version = _required_string(
        receipt.get("compiler_version"), "receipt compiler version"
    )
    if compiler_version != f"clang version {CLANG_JSON_DUMPER_VERSION}":
        _fail(
            f"{selection_id}: no source-bound JSON location semantics for {compiler_version}"
        )
    if _sha256(compiler) != receipt.get("compiler_sha256"):
        _fail(f"{selection_id}: receipt-bound Clang binary changed")
    resource_dir = Path(
        _required_string(receipt.get("resource_dir"), "resource directory")
    )
    resource_probe = Path(
        _required_string(receipt.get("resource_probe"), "resource probe")
    )
    if not resource_probe.is_relative_to(resource_dir) or _sha256(
        resource_probe
    ) != receipt.get("resource_probe_sha256"):
        _fail(f"{selection_id}: Clang resource directory identity changed")
    effective_clang_value = selected_row.get("effective_clang")
    if not isinstance(effective_clang_value, dict):
        _fail(f"{selection_id}: effective Clang identity is absent")
    effective_clang = cast("dict[str, object]", effective_clang_value)
    if effective_clang.get("compiler_path") != str(compiler):
        _fail(f"{selection_id}: preflight compiler path differs from build receipt")
    if effective_clang.get("compiler_sha256") != receipt.get("compiler_sha256"):
        _fail(f"{selection_id}: preflight compiler hash differs from build receipt")
    if effective_clang.get("resource_probe_sha256") != receipt.get(
        "resource_probe_sha256"
    ):
        _fail(f"{selection_id}: preflight resource probe differs from build receipt")
    cwd = Path(
        _required_string(
            selected_row.get("profile_working_directory"), "profile working directory"
        )
    ).resolve()
    if not cwd.is_dir():
        _fail(f"{selection_id}: profile working directory is missing")
    if not isinstance(profile_entry.get("coverage_state"), str):
        _fail(f"{selection_id}: profile coverage state is absent")
    compile_database_value = preflight.get("compile_database")
    if not isinstance(compile_database_value, dict):
        _fail(f"{selection_id}: compile database binding is absent")
    compile_database = cast("dict[str, object]", compile_database_value)
    compile_database_path = Path(
        _required_string(compile_database.get("path"), "compile database path")
    )
    compile_database_sha256 = _required_string(
        compile_database.get("sha256_before"), "compile database digest"
    )
    if (
        not compile_database_path.is_file()
        or _sha256(compile_database_path) != compile_database_sha256
    ):
        _fail(f"{selection_id}: compile database changed")
    return {
        "selection_id": selection_id,
        "cohort_row": cohort_row,
        "cohort_manifest_path": str(cohort_manifest_path.resolve()),
        "cohort_manifest_sha256": _sha256(cohort_manifest_path),
        "profile_manifest_path": str(profile_manifest_path.resolve()),
        "profile_manifest_sha256": _sha256(profile_manifest_path),
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": profile_digest,
        "source_path": str(source_path),
        "source": source,
        "source_sha256": source_digest,
        "original_driver_argv0": original_argv[0],
        "original_driver": selected_row.get("original_driver"),
        "original_argv": original_argv,
        "effective_compiler_path": str(compiler),
        "effective_compiler_sha256": receipt.get("compiler_sha256"),
        "effective_compiler_version": compiler_version,
        "resource_dir": str(resource_dir),
        "resource_probe": str(resource_probe),
        "resource_probe_sha256": receipt.get("resource_probe_sha256"),
        "build_receipt_path": str(build_receipt_path.resolve()),
        "build_receipt_sha256": receipt_digest,
        "adapted_argv": adapted_argv,
        "working_directory": str(cwd),
        "dependency_count": len(dependencies),
        "dependency_closure_status": profile_entry.get("dependency_closure_status"),
        "coverage_state": profile_entry.get("coverage_state"),
        "compile_database_path": str(compile_database_path.resolve()),
        "compile_database_sha256": compile_database_sha256,
    }


def _write_exclusive(path: Path, data: bytes) -> None:
    """Write immutable evidence bytes without replacing an existing file.

    Parameters
    ----------
    path : pathlib.Path
        Destination file.
    data : bytes
        Content to persist.

    Returns
    -------
    None
        The content is written without replacing an existing destination.
    """
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def reference_invocation(identity: dict[str, object]) -> tuple[list[str], str]:
    """Build the CLI command while preserving original driver-mode argv0.

    Parameters
    ----------
    identity : dict[str, object]
        Validated profile and compiler identity.

    Returns
    -------
    tuple[list[str], str]
        Process argv and receipt-bound executable path. The argv0 remains the
        original compile driver's spelling (for example ``cc`` or ``c++``).
    """
    args = [
        _required_string(identity.get("original_driver_argv0"), "original argv0"),
        *[str(arg) for arg in cast("list[object]", identity["adapted_argv"])],
        "-Xclang",
        "-ast-dump=json",
        _required_string(identity.get("source_path"), "source path"),
    ]
    executable = _required_string(
        identity.get("effective_compiler_path"), "effective compiler executable"
    )
    return args, executable


def capture_one(
    identity: dict[str, object],
    output_directory: Path,
    timeout_seconds: int = 900,
) -> dict[str, object]:
    """Capture one AST reference and persist terminal evidence before parsing.

    Parameters
    ----------
    identity : dict[str, object]
        Validated source/profile/compiler identity.
    output_directory : pathlib.Path
        New, exclusive per-selection output directory.
    timeout_seconds : int, optional
        Native CLI timeout.

    Returns
    -------
    dict[str, object]
        Terminal capture record and normalized partial reference facts.
    """
    selection_id = str(identity["selection_id"])
    output_directory.mkdir(parents=True, exist_ok=False)
    args, executable = reference_invocation(identity)
    stdout_path = output_directory / "clang-ast.stdout.bin"
    stderr_path = output_directory / "clang-ast.stderr.bin"
    status_path = output_directory / "clang-ast.exit-status.txt"
    timed_out = False
    launch_error: str | None = None
    return_code: int | None = None
    extractor_path = Path(__file__).resolve()
    extractor_sha256_before = _sha256(extractor_path)
    native_started = time.monotonic()
    try:
        with (
            stdout_path.open("xb") as stdout_stream,
            stderr_path.open("xb") as stderr_stream,
        ):
            try:
                result = subprocess.run(
                    args,
                    executable=executable,
                    cwd=str(identity["working_directory"]),
                    stdout=stdout_stream,
                    stderr=stderr_stream,
                    check=False,
                    timeout=timeout_seconds,
                )
                return_code = result.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                return_code = None
            except OSError as exc:
                launch_error = f"{type(exc).__name__}: {exc}"
                stderr_stream.write(launch_error.encode("utf-8", errors="replace"))
            stdout_stream.flush()
            os.fsync(stdout_stream.fileno())
            stderr_stream.flush()
            os.fsync(stderr_stream.fileno())
    except OSError as exc:
        if launch_error is None:
            launch_error = f"{type(exc).__name__}: {exc}"
        return_code = None
        for path in (stdout_path, stderr_path):
            if not path.exists():
                _write_exclusive(path, b"")
    native_duration_seconds = time.monotonic() - native_started
    extractor_sha256_after = _sha256(extractor_path)
    extractor_changed_during_capture = extractor_sha256_before != extractor_sha256_after
    _write_exclusive(
        status_path,
        f"{return_code if return_code is not None else 'timeout' if timed_out else 'launch_error'}\n".encode(),
    )
    terminal: dict[str, object] = {
        "schema": REFERENCE_SCHEMA,
        "identity": selection_id,
        "capture_kind": "independent_clang_cli_ast_dump",
        "interpretation": "clang_parity_only_same_compiler_not_compiler_independent_truth",
        "reference_extractor_path": str(extractor_path),
        "reference_extractor_sha256": extractor_sha256_before,
        "reference_extractor_sha256_after_capture": extractor_sha256_after,
        "reference_extractor_changed_during_capture": extractor_changed_during_capture,
        "clang_json_dumper_source_version": CLANG_JSON_DUMPER_VERSION,
        "clang_json_dumper_source_url": CLANG_JSON_DUMPER_SOURCE,
        "clang_json_dumper_source_lines": list(CLANG_JSON_DUMPER_SOURCE_LINES),
        "clang_json_dumper_source_excerpt_sha256": CLANG_JSON_DUMPER_SOURCE_EXCERPT_SHA256,
        "location_file_binding_policy": "global_LastLocFilename_in_serialized_location_order; includedFrom_does_not_update_state",
        "location_macro_policy": "spellingLoc_is_serialized_before_expansionLoc; each updates_global_location_state",
        "location_line_column_policy": "line_is_actual_source_line; col_is_presumed_column",
        "argv": args,
        "argv0_original_driver": identity["original_driver_argv0"],
        "effective_executable": identity["effective_compiler_path"],
        "working_directory": identity["working_directory"],
        "source_path": identity["source_path"],
        "source_sha256": identity["source_sha256"],
        "profile_path": identity["profile_path"],
        "profile_sha256": identity["profile_sha256"],
        "compile_database_path": identity["compile_database_path"],
        "compile_database_sha256": identity["compile_database_sha256"],
        "build_receipt_path": identity["build_receipt_path"],
        "build_receipt_sha256": identity["build_receipt_sha256"],
        "clang_binary_sha256": identity["effective_compiler_sha256"],
        "clang_version_from_receipt": identity["effective_compiler_version"],
        "resource_dir": identity["resource_dir"],
        "resource_probe_sha256": identity["resource_probe_sha256"],
        "dependency_count": identity["dependency_count"],
        "dependency_closure_status": identity["dependency_closure_status"],
        "profile_coverage_state": identity["coverage_state"],
        "return_code": return_code,
        "native_duration_seconds": native_duration_seconds,
        "timed_out": timed_out,
        "launch_error": launch_error,
        "raw_stdout_path": str(stdout_path.resolve()),
        "raw_stdout_sha256": _sha256(stdout_path),
        "raw_stdout_bytes": stdout_path.stat().st_size,
        "raw_stderr_path": str(stderr_path.resolve()),
        "raw_stderr_sha256": _sha256(stderr_path),
        "raw_stderr_bytes": stderr_path.stat().st_size,
        "exit_status_path": str(status_path.resolve()),
    }
    terminal_path = output_directory / "terminal-record.json"
    _write_exclusive(
        terminal_path, (json.dumps(terminal, indent=2, sort_keys=True) + "\n").encode()
    )
    terminal["terminal_record_path"] = str(terminal_path.resolve())
    if (
        return_code != 0
        or timed_out
        or launch_error is not None
        or extractor_changed_during_capture
    ):
        _write_exclusive(
            output_directory / "normalization-record.json",
            (
                b'{"status":"not_run_extractor_changed_during_capture"}\n'
                if extractor_changed_during_capture
                else b'{"status":"not_run_native_capture_incomplete"}\n'
            ),
        )
        return {"terminal": terminal, "normalized": None}
    try:
        with stdout_path.open("r", encoding="utf-8") as stdout_stream:
            ast_value = json.load(stdout_stream)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        terminal["parse_error"] = f"{type(exc).__name__}: {exc}"
        _write_exclusive(
            output_directory / "normalization-record.json",
            (
                json.dumps(
                    {
                        "status": "failed_ast_json_parse",
                        "error": terminal["parse_error"],
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode(),
        )
        return {"terminal": terminal, "normalized": None}
    if not isinstance(ast_value, dict):
        terminal["parse_error"] = "top-level AST JSON is not an object"
        _write_exclusive(
            output_directory / "normalization-record.json",
            b'{"status":"failed_ast_json_parse","error":"top-level AST JSON is not an object"}\n',
        )
        return {"terminal": terminal, "normalized": None}
    source = identity.get("source")
    if not isinstance(source, bytes):
        _fail(f"{selection_id}: bound source bytes are absent")
    normalized = normalize_ast(
        ast_value,
        Path(str(identity["source_path"])),
        source,
        Path(str(identity["working_directory"])),
    )
    category_value = normalized.get("required_category_coverage")
    if isinstance(category_value, dict):
        category_coverage = cast("dict[str, object]", category_value)
        diagnostic_lines = [
            line
            for line in stderr_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        category_coverage["native_parse_and_diagnostics"] = {
            "status": "accepted_with_diagnostics" if diagnostic_lines else "accepted",
            "reason": "receipt-bound Clang CLI returned zero; raw stderr is retained",
            "diagnostic_line_count": len(diagnostic_lines),
        }
    normalized_path = output_directory / "normalized-reference.json"
    _write_exclusive(
        normalized_path,
        (json.dumps(normalized, indent=2, sort_keys=True) + "\n").encode(),
    )
    normalized_facts_value = normalized.get("facts")
    normalized_facts = cast(
        "dict[str, object]",
        normalized_facts_value if isinstance(normalized_facts_value, dict) else {},
    )
    normalization_record = {
        "status": "normalized_partial_clang_reference",
        "normalized_reference_path": str(normalized_path.resolve()),
        "normalized_fact_counts": {
            name: len(rows)
            for name, rows in normalized_facts.items()
            if isinstance(rows, list)
        },
        "ungraded_counts": normalized["ungraded_counts"],
        "whole_file_parity": False,
    }
    _write_exclusive(
        output_directory / "normalization-record.json",
        (json.dumps(normalization_record, indent=2, sort_keys=True) + "\n").encode(),
    )
    terminal["normalization_record_path"] = str(
        (output_directory / "normalization-record.json").resolve()
    )
    return {"terminal": terminal, "normalized": normalized}


def _validate_scope_rows(
    scope_manifest: dict[str, object], pilot_rows: list[dict[str, object]]
) -> dict[str, int]:
    """Validate an explicit selection scope against its source pilot rows.

    Parameters
    ----------
    scope_manifest : dict[str, object]
        Immutable source-joined cohort plan containing ``cohort_rows``.
    pilot_rows : list[dict[str, object]]
        Broader pilot manifest rows used to bind prepared profiles.

    Returns
    -------
    dict[str, int]
        Language counts derived from the explicit scope rows.
    """
    scope_rows = _object_rows(scope_manifest.get("cohort_rows"), "scope.cohort_rows")
    if not scope_rows:
        _fail("scope.cohort_rows must not be empty")
    pilot_by_id = {str(row.get("selection_id")): row for row in pilot_rows}
    scope_ids: set[str] = set()
    language_counts: Counter[str] = Counter()
    for row in scope_rows:
        selection_id = _required_string(row.get("selection_id"), "scope selection_id")
        if selection_id in scope_ids:
            _fail(f"scope contains duplicate selection ID: {selection_id}")
        scope_ids.add(selection_id)
        pilot_row = pilot_by_id.get(selection_id)
        if pilot_row is None:
            _fail(f"scope selection is absent from pilot manifest: {selection_id}")
        for field in ("source_path", "source_sha256", "repository_relative_path"):
            if row.get(field) != pilot_row.get(field):
                _fail(f"{selection_id}: scope and pilot {field} differ")
        classification = row.get("classification")
        if not isinstance(classification, dict):
            _fail(f"{selection_id}: scope language classification is absent")
        language = classification.get("analyzer")
        if language not in {"c", "cpp"}:
            _fail(f"{selection_id}: unsupported scope analyzer language {language!r}")
        language_counts[cast("str", language)] += 1
    summary_value = scope_manifest.get("cohort_summary")
    if isinstance(summary_value, dict):
        summary_rows = summary_value.get("cohort_rows")
        if summary_rows is not None and summary_rows != len(scope_rows):
            _fail("scope cohort_summary row count differs from cohort_rows")
        summary_languages = summary_value.get("language_counts")
        if summary_languages is not None and summary_languages != dict(language_counts):
            _fail("scope cohort_summary language counts differ from cohort_rows")
    return dict(sorted(language_counts.items()))


def run_reference_lane(  # noqa: C901, PLR0913 -- explicit cohort and terminal gates
    cohort_manifest_path: Path,
    scope_manifest_path: Path,
    profile_manifest_root: Path,
    preflight_path: Path,
    build_receipt_path: Path,
    output_root: Path,
    selection_ids: list[str],
) -> dict[str, object]:
    """Run selected exact profiles while retaining the complete cohort denominator.

    Parameters
    ----------
    cohort_manifest_path : pathlib.Path
        Broader pilot cohort manifest used to validate profile identities.
    scope_manifest_path : pathlib.Path
        Explicit source-joined selection scope whose denominator is graded.
    profile_manifest_root : pathlib.Path
        Root of prepared per-selection profiles.
    preflight_path : pathlib.Path
        Profile API preflight with effective Clang argv and receipts.
    build_receipt_path : pathlib.Path
        Clang binary/resource identity receipt.
    output_root : pathlib.Path
        New immutable run directory.
    selection_ids : list[str]
        Rows to capture in this attempt.

    Returns
    -------
    dict[str, object]
        Full-scope coverage map and per-row terminal results.
    """
    if output_root.exists():
        _fail(f"output identity already exists: {output_root}")
    cohort = _read_object(cohort_manifest_path)
    rows = _object_rows(cohort.get("rows"), "cohort.rows")
    scope_manifest = _read_object(scope_manifest_path)
    scope_rows = _object_rows(scope_manifest.get("cohort_rows"), "scope.cohort_rows")
    language_counts = _validate_scope_rows(scope_manifest, rows)
    cohort_manifest_sha256 = _sha256(cohort_manifest_path)
    scope_manifest_sha256 = _sha256(scope_manifest_path)
    selected_set = set(selection_ids)
    if len(selected_set) != len(selection_ids):
        _fail("selection IDs must be unique")
    cohort_ids = {str(row.get("selection_id")) for row in rows}
    scope_ids = {str(row.get("selection_id")) for row in scope_rows}
    unknown = sorted(selected_set - cohort_ids)
    if unknown:
        _fail(f"selection IDs absent from cohort: {unknown}")
    outside_scope = sorted(selected_set - scope_ids)
    if outside_scope:
        _fail(f"selected profiles are outside the explicit scope: {outside_scope}")
    identities = [
        _load_profile_inputs(
            selection_id,
            cohort_manifest_path,
            profile_manifest_root,
            preflight_path,
            build_receipt_path,
        )
        for selection_id in selection_ids
    ]
    output_root.mkdir(parents=True, exist_ok=False)
    results: list[dict[str, object]] = []
    normalized_by_id: dict[str, dict[str, object]] = {}
    selection_output = output_root / "selections"
    selection_output.mkdir()
    for identity in identities:
        selection_id = str(identity["selection_id"])
        result = capture_one(identity, selection_output / selection_id)
        terminal = result["terminal"]
        if not isinstance(terminal, dict):
            _fail(f"{selection_id}: terminal record was not returned")
        post_capture_path = (
            selection_output / selection_id / "post-capture-input-validation.json"
        )
        input_fields = (
            "cohort_manifest_sha256",
            "profile_manifest_sha256",
            "profile_sha256",
            "source_path",
            "source_sha256",
            "original_argv",
            "adapted_argv",
            "effective_compiler_path",
            "effective_compiler_sha256",
            "effective_compiler_version",
            "resource_probe_sha256",
            "build_receipt_sha256",
            "compile_database_path",
            "compile_database_sha256",
            "dependency_count",
            "dependency_closure_status",
            "working_directory",
        )
        changed_inputs: dict[str, dict[str, object]] = {}
        revalidation_error: str | None = None
        try:
            after_identity = _load_profile_inputs(
                selection_id,
                cohort_manifest_path,
                profile_manifest_root,
                preflight_path,
                build_receipt_path,
            )
            for field in input_fields:
                if identity.get(field) != after_identity.get(field):
                    changed_inputs[field] = {
                        "before": identity.get(field),
                        "after": after_identity.get(field),
                    }
        except (ReferenceInputError, OSError) as exc:
            revalidation_error = f"{type(exc).__name__}: {exc}"
        if _sha256(cohort_manifest_path) != cohort_manifest_sha256:
            changed_inputs["cohort_manifest_sha256"] = {
                "before": cohort_manifest_sha256,
                "after": _sha256(cohort_manifest_path),
            }
        if _sha256(scope_manifest_path) != scope_manifest_sha256:
            changed_inputs["scope_manifest_sha256"] = {
                "before": scope_manifest_sha256,
                "after": _sha256(scope_manifest_path),
            }
        input_validation = {
            "schema": REFERENCE_SCHEMA,
            "selection_id": selection_id,
            "status": "passed"
            if not changed_inputs and revalidation_error is None
            else "failed",
            "validated_after_native_capture": True,
            "raw_terminal_record_path": terminal.get("terminal_record_path"),
            "raw_stdout_sha256": terminal.get("raw_stdout_sha256"),
            "changed_inputs": changed_inputs,
            "revalidation_error": revalidation_error,
        }
        _write_exclusive(
            post_capture_path,
            (json.dumps(input_validation, indent=2, sort_keys=True) + "\n").encode(),
        )
        terminal["post_capture_input_validation_path"] = str(
            post_capture_path.resolve()
        )
        terminal["post_capture_input_validation_status"] = input_validation["status"]
        results.append(cast("dict[str, object]", terminal))
        normalized_value = result.get("normalized")
        if input_validation["status"] == "passed" and isinstance(
            normalized_value, dict
        ):
            normalized_by_id[selection_id] = cast("dict[str, object]", normalized_value)
    by_id = {str(result["identity"]): result for result in results}
    coverage_rows = []
    aggregate_coverage: dict[str, Counter[str]] = {
        category: Counter() for category in REQUIRED_CATEGORIES
    }
    for row in scope_rows:
        selection_id = str(row.get("selection_id"))
        terminal = by_id.get(selection_id)
        normalized = normalized_by_id.get(selection_id)
        coverage_value = (
            normalized.get("required_category_coverage") if normalized else None
        )
        if isinstance(coverage_value, dict):
            row_coverage = cast("dict[str, object]", coverage_value)
        else:
            row_coverage = {
                category: {
                    "status": "ungraded",
                    "reason": (
                        "capture input guard failed; raw reference remains retained"
                        if terminal
                        and terminal.get("post_capture_input_validation_status")
                        != "passed"
                        else "no independent CLI AST capture in this attempt"
                    ),
                }
                for category in REQUIRED_CATEGORIES
            }
        for category in REQUIRED_CATEGORIES:
            category_result = row_coverage.get(category)
            category_status = (
                str(category_result.get("status"))
                if isinstance(category_result, dict)
                else "ungraded"
            )
            aggregate_coverage[category][category_status] += 1
        coverage_rows.append(
            {
                "selection_id": selection_id,
                "repository_relative_path": row.get("repository_relative_path"),
                "source_path": row.get("source_path"),
                "source_sha256": row.get("source_sha256"),
                "capture_state": "captured"
                if terminal
                else "not_captured_in_this_attempt",
                "terminal_record_path": terminal.get("terminal_record_path")
                if terminal
                else None,
                "required_category_coverage": row_coverage,
                "whole_file_parity": False,
            }
        )
    receipt = {
        "schema": REFERENCE_SCHEMA,
        "identity": output_root.name,
        "status": "clang_parity_partial_no_admissions",
        "interpretation": "independent_cli_ast_extraction_same_compiler_not_compiler_independent_truth",
        "pilot_manifest": str(cohort_manifest_path.resolve()),
        "pilot_manifest_sha256": cohort_manifest_sha256,
        "scope_manifest": str(scope_manifest_path.resolve()),
        "scope_manifest_sha256": scope_manifest_sha256,
        "full_cohort_scope": scope_manifest.get("scope"),
        "full_cohort_rows": len(scope_rows),
        "language_counts": language_counts,
        "repository_counts": dict(
            sorted(
                Counter(
                    str(row.get("repository", "unknown")) for row in scope_rows
                ).items()
            )
        ),
        "captured_selection_ids": selection_ids,
        "required_categories": list(REQUIRED_CATEGORIES),
        "supported_categories": sorted(SUPPORTED_CATEGORIES),
        "required_category_coverage_across_full_cohort": {
            category: {
                "rows_by_status": dict(sorted(counts.items())),
                "whole_file_complete_rows": 0,
            }
            for category, counts in aggregate_coverage.items()
        },
        "whole_file_semantic_closure_claimed": False,
        "admissions": 0,
        "results": results,
        "cohort_coverage": coverage_rows,
    }
    receipt_path = output_root / "reference-lane-receipt.json"
    _write_exclusive(
        receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    )
    return receipt


def _parse_args() -> argparse.Namespace:
    """Parse the reference-lane command line.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.Namespace
        Parsed input paths and selection IDs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-manifest", type=Path, required=True)
    parser.add_argument("--scope-manifest", type=Path, required=True)
    parser.add_argument("--profile-manifest-root", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--build-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--selection-id", action="append", required=True)
    return parser.parse_args()


def main() -> int:
    """Run the selected independent Clang reference captures.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Zero after all selected captures reach a recorded terminal state.
    """
    args = _parse_args()
    receipt = run_reference_lane(
        args.cohort_manifest,
        args.scope_manifest,
        args.profile_manifest_root,
        args.preflight,
        args.build_receipt,
        args.output_root,
        args.selection_id,
    )
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "captured": receipt["captured_selection_ids"],
                "receipt": str(args.output_root / "reference-lane-receipt.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
