"""C language analyzer backed by tree-sitter.

Responsibilities
----------------
- Initialize the tree-sitter C parser and derive module and function stable IDs.
- Walk parse nodes to extract imports, declarations, call sites, and normalized artifacts.
- Translate the collected metadata into `AnalysisResult` objects for persistence.

Design principles
-----------------
The analyzer confines tree-sitter interaction to this module so language-specific logic stays isolated and deterministic.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the C-family analysis path for ADR-004.

Parameters
----------
None

Returns
-------
None
    C-owned parsing and normalized source artifacts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import replace
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from codira.contracts import LanguageAnalyzer

from tree_sitter import Node

from .c_parameter_macros import ParameterMacro, macro_parameter_name, parameter_macros
from .c_parser import _new_parser as _new_parser
from .c_include_context import read_include_context, include_identity_matches
from .c_declaration_macros import (
    ExpandedDeclaration,
    ExpansionRejected,
    declaration_expansions,
    project_empty_function_macro_arguments,
)
from codira.analysis_inputs import validate_analysis_input_fingerprint
from codira.generated import (
    GeneratedCallableProvenance,
    GeneratedTokenProvenance,
    MacroInputProvenance,
)

from .c_conditionals import CParseView, c_parse_views
from .c_preprocessing import (
    _is_complex_operator_call,
    _original_declaration_start,
    _parse_c_source,
)
from .c_statement_macros import projected_statement_macro_name

from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisCoverageState,
    AnalysisDiagnostic,
    AnalysisResult,
    AnalysisStatus,
    CallSite,
    DeclarationArtifact,
    DeclarationKind,
    DocumentationArtifact,
    DocumentationKind,
    EnumMemberArtifact,
    FunctionArtifact,
    ImportArtifact,
    ImportKind,
    ModuleArtifact,
    tree_sitter_recovery_status,
)
from codira.plugin_config import (
    AnalyzerPathFilters,
    analyzer_json_schema,
    analyzer_path_allowed,
    analyzer_path_filters_from_config,
    boolean_property,
    plugin_configuration_fingerprint,
)

_C_SUFFIXES = {".c", ".h"}
__all__ = ["CAnalyzer", "_disambiguate_function_stable_ids", "build_analyzer"]
_TYPE_LIKE_NAMES = {
    "bool",
    "char",
    "double",
    "float",
    "int",
    "long",
    "short",
    "size_t",
    "uint8_t",
    "uint16_t",
    "uint32_t",
    "uint64_t",
    "int8_t",
    "int16_t",
    "int32_t",
    "int64_t",
    "void",
}
_C_SYSTEM_FUNCTIONS = frozenset(
    {
        "calloc",
        "fclose",
        "fopen",
        "fprintf",
        "free",
        "fwrite",
        "malloc",
        "memcmp",
        "memcpy",
        "memmove",
        "memset",
        "printf",
        "puts",
        "snprintf",
        "sprintf",
        "strcmp",
        "strcpy",
        "strlen",
        "strncmp",
    }
)
_C_MACROS = frozenset(
    {
        "Py_DECREF",
        "Py_INCREF",
        "Py_XDECREF",
        "Py_XINCREF",
        "assert",
    }
)


def _decode_source_text(source: bytes) -> str:
    """
    Decode one source fragment with a deterministic legacy fallback.

    Parameters
    ----------
    source : bytes
        Raw source bytes to decode.

    Returns
    -------
    str
        Text decoded as UTF-8 when possible, otherwise Latin-1.
    """
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError:
        return source.decode("latin-1")


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive the logical module name for one C source path.

    Parameters
    ----------
    path : pathlib.Path
        Source file being analyzed.
    root : pathlib.Path
        Repository root used for relative module naming.

    Returns
    -------
    str
        Dotted module identity derived from the relative file path.
    """
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


def _module_stable_id(path: Path, root: Path) -> str:
    """
    Build the durable identity for one C-family module.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable C-family module identity.
    """
    return f"c:module:{path.relative_to(root).as_posix()}"


def _symbol_owner_id(path: Path, root: Path) -> str:
    """
    Build the file-scoped owner identity for C symbols.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Repo-relative owner identity that preserves the file suffix.
    """
    return path.relative_to(root).as_posix()


def _function_stable_id(owner_id: str, function_name: str) -> str:
    """
    Build the durable identity for one C function.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    function_name : str
        Unqualified function name.

    Returns
    -------
    str
        Durable C function identity.
    """
    return f"c:function:{owner_id}:{function_name}"


def _declaration_stable_id(
    owner_id: str,
    kind: DeclarationKind,
    declaration_name: str,
) -> str:
    """
    Build the durable identity for one top-level C declaration.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    kind : {"constant", "macro", "struct", "union", "enum", "typedef"}
        Stable declaration classifier.
    declaration_name : str
        Exposed declaration name.

    Returns
    -------
    str
        Durable C declaration identity.
    """
    return f"c:{kind}:{owner_id}:{declaration_name}"


def _enum_member_stable_id(
    owner_id: str,
    enum_name: str,
    ordinal: int,
) -> str:
    """
    Build the durable identity for one C enum member declaration.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    enum_name : str
        Owning enum declaration name.
    ordinal : int
        Deterministic declaration order among members for the enum.

    Returns
    -------
    str
        Durable C enum-member identity.
    """
    return f"c:enum_member:{owner_id}:{enum_name}:{ordinal}"


def _node_text(node: Node, source: bytes) -> str:
    """
    Decode the source text owned by one syntax node.

    Parameters
    ----------
    node : tree_sitter.Node
        Syntax node whose text should be decoded.
    source : bytes
        Full source buffer.

    Returns
    -------
    str
        Decoded node text with a deterministic legacy fallback.
    """
    return _decode_source_text(source[node.start_byte : node.end_byte])


def _comment_to_summary(text: str) -> str | None:
    """
    Normalize one raw C comment block into summary text.

    Parameters
    ----------
    text : str
        Raw comment text including delimiters.

    Returns
    -------
    str | None
        Normalized summary text, or ``None`` when no content remains.
    """
    stripped = text.strip()
    if stripped.startswith("/*"):
        body = stripped.removeprefix("/*").removesuffix("*/")
        lines = [line.strip().lstrip("*").strip() for line in body.splitlines()]
    else:
        lines = [
            line.strip().removeprefix("//").strip() for line in stripped.splitlines()
        ]

    normalized_lines = [line for line in lines if line]
    if not normalized_lines:
        return None
    return "\n".join(normalized_lines)


def _comment_to_doxygen_text(text: str) -> str | None:
    """
    Normalize one raw Doxygen comment block into documentation text.

    Parameters
    ----------
    text : str
        Raw comment text including delimiters.

    Returns
    -------
    str | None
        Normalized Doxygen text, or ``None`` when the comment is not Doxygen.
    """
    stripped = text.strip()
    if stripped.startswith(("/**", "/*!")):
        body = stripped[3:].removesuffix("*/")
        lines = [line.strip().lstrip("*").strip() for line in body.splitlines()]
    elif stripped.startswith(("///", "//!")):
        lines = []
        for line in stripped.splitlines():
            normalized = line.strip()
            if normalized.startswith(("///", "//!")):
                lines.append(normalized[3:].strip())
            else:
                return None
    else:
        return None

    normalized_lines = [line for line in lines if line]
    if not normalized_lines:
        return None
    return "\n".join(normalized_lines)


def _leading_module_doxygen(
    root: Node, source: bytes
) -> tuple[str, int, int | None] | None:
    """
    Extract the first leading Doxygen file comment as documentation text.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, int, int | None] | None
        Normalized text plus source coordinates, or ``None`` when absent.
    """
    for index, child in enumerate(root.children):
        if child.type == "comment":
            text = _comment_to_doxygen_text(_node_text(child, source))
            if text is None:
                return None
            next_non_comment = next(
                (
                    sibling
                    for sibling in root.children[index + 1 :]
                    if sibling.type != "comment"
                ),
                None,
            )
            if (
                next_non_comment is not None
                and next_non_comment.type != "preproc_include"
            ):
                return None
            return text, child.start_point.row + 1, child.end_point.row + 1
        if child.type != "preproc_include":
            return None
    return None


def _leading_module_comment(root: Node, source: bytes) -> str | None:
    """
    Extract the first leading file comment as module summary text.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Normalized leading comment summary, or ``None`` when absent.
    """
    for child in root.children:
        if child.type == "comment":
            return _comment_to_summary(_node_text(child, source))
        if child.type != "preproc_include":
            return None
    return None


def _attached_doxygen_comment_map(
    root: Node, source: bytes
) -> dict[int, tuple[str, int, int | None]]:
    """
    Map declaration start bytes to nearby leading Doxygen comments.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    dict[int, tuple[str, int, int | None]]
        Doxygen text and source coordinates keyed by declaration start line.
    """
    attached: dict[int, tuple[str, int, int | None]] = {}
    pending_comment: tuple[str, int, int | None] | None = None
    pending_end_row: int | None = None

    for child in _top_level_nodes(root):
        if child.type == "comment":
            text = _comment_to_doxygen_text(_node_text(child, source))
            pending_comment = (
                (text, child.start_point.row + 1, child.end_point.row + 1)
                if text is not None
                else None
            )
            pending_end_row = child.end_point.row
            continue

        if pending_comment is not None and pending_end_row is not None:
            if child.start_point.row - pending_end_row <= 2:
                start = _original_declaration_start(child, source)
                attached[source.count(b"\n", 0, start) + 1] = pending_comment
            pending_comment = None
            pending_end_row = None

    return attached


def _attached_comment_map(root: Node, source: bytes) -> dict[int, str]:
    """
    Map declaration start bytes to nearby leading comment summaries.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    dict[int, str]
        Attached comment summaries keyed by declaration start byte.
    """
    attached: dict[int, str] = {}
    pending_comment: str | None = None
    pending_end_row: int | None = None

    for child in _top_level_nodes(root):
        if child.type == "comment":
            pending_comment = _comment_to_summary(_node_text(child, source))
            pending_end_row = child.end_point.row
            continue

        if pending_comment is not None and pending_end_row is not None:
            if child.start_point.row - pending_end_row <= 2:
                attached[child.start_byte] = pending_comment
            pending_comment = None
            pending_end_row = None

    return attached


def _named_descendants(node: Node) -> list[Node]:
    """
    Collect named descendants of one syntax node in source order.

    Parameters
    ----------
    node : tree_sitter.Node
        Parent syntax node.

    Returns
    -------
    list[tree_sitter.Node]
        Named descendant nodes in deterministic source order.
    """
    descendants: list[Node] = []
    stack = list(reversed(node.named_children))

    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(reversed(current.named_children))

    return descendants


def _unwrap_declarator_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the identifier owned by one declarator node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may nest pointers or arrays.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Identifier text when resolvable.
    """
    if node.type == "function_declarator":
        function_name = _function_declarator_name(node, source)
        if function_name is not None:
            return function_name

    if node.type in {"identifier", "field_identifier"}:
        return _node_text(node, source)

    child = node.child_by_field_name("declarator")
    if child is not None:
        return _unwrap_declarator_name(child, source)

    for named_child in node.named_children:
        name = _unwrap_declarator_name(named_child, source)
        if name is not None:
            return name
    return None


def _function_declarator_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the callable identifier owned by one function declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator that may include annotations or parse errors.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Callable identifier text when resolvable.
    """
    direct_declarator = node.child_by_field_name("declarator")
    if direct_declarator is not None and direct_declarator.type == "identifier":
        direct_name = _node_text(direct_declarator, source)
        error_name = _error_identifier_name(node, source)
        if error_name is not None and _looks_like_macro_or_type_name(direct_name):
            return error_name

    macro_wrapped_name = _function_macro_wrapper_name(node, source)
    if macro_wrapped_name is not None:
        return macro_wrapped_name

    if direct_declarator is None or direct_declarator.type != "identifier":
        return None
    if not _looks_like_annotation_macro_name(_node_text(direct_declarator, source)):
        return None
    return _annotated_function_call_name(node, source)


def _annotated_function_call_name(node: Node, source: bytes) -> str | None:
    """
    Resolve a callable name from a macro-annotated call-like declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator whose real callable name may appear in a nested
        call expression.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Callable identifier text when the annotation pattern is present.
    """
    for named_child in reversed(node.named_children):
        if named_child.type != "call_expression":
            continue
        arguments = named_child.child_by_field_name("arguments")
        if arguments is None or not arguments.named_children:
            continue
        function_node = named_child.child_by_field_name("function")
        if function_node is None:
            continue
        name = _unwrap_declarator_name(function_node, source)
        if name is not None:
            return name
    return None


def _looks_like_macro_or_type_name(name: str) -> bool:
    """
    Decide whether one declarator token looks like a macro or a type name.

    Parameters
    ----------
    name : str
        Candidate declarator token.

    Returns
    -------
    bool
        ``True`` when the token is unlikely to be the real callable name.
    """
    if name in _TYPE_LIKE_NAMES or name.endswith("_t"):
        return True
    return _looks_like_annotation_macro_name(name)


def _looks_like_annotation_macro_name(name: str) -> bool:
    """
    Decide whether one declarator token looks like an annotation macro.

    Parameters
    ----------
    name : str
        Candidate declarator token.

    Returns
    -------
    bool
        ``True`` when the token is all-uppercase or underscore-style text.
    """
    has_alpha = any(char.isalpha() for char in name)
    if not has_alpha:
        return False
    return all(not char.isalpha() or char.isupper() for char in name)


def _error_identifier_name(node: Node, source: bytes) -> str | None:
    """
    Extract one identifier-like token from an ``ERROR`` child when present.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may include a parse-error placeholder.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Recovered identifier text when the ``ERROR`` child looks usable.
    """
    for named_child in node.named_children:
        if named_child.type != "ERROR":
            continue
        text = _node_text(named_child, source).strip()
        if not text:
            continue
        if "::" in text or "(" in text or ")" in text or "[" in text or "]" in text:
            continue
        if not (text[0].isalpha() or text[0] == "_"):
            continue
        if any(not (char.isalnum() or char == "_") for char in text):
            continue
        return text
    return None


def _function_macro_wrapper_name(node: Node, source: bytes) -> str | None:
    """
    Resolve a function name wrapped by a macro-style declarator.

    Parameters
    ----------
    node : tree_sitter.Node
        Function declarator that may wrap the real name in a macro call.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Wrapped function name when the declarator matches the macro pattern.
    """
    nested = node.child_by_field_name("declarator")
    if nested is None or nested.type != "function_declarator":
        return None

    parameter_list = nested.child_by_field_name("parameters")
    if parameter_list is None or len(parameter_list.named_children) != 1:
        return None

    parameter = parameter_list.named_children[0]
    if parameter.type != "parameter_declaration":
        return None
    if parameter.child_by_field_name("declarator") is not None:
        return None

    for named_child in parameter.named_children:
        if named_child.type in {"identifier", "type_identifier", "field_identifier"}:
            return _node_text(named_child, source)
    return None


def _extract_parameter_names(
    parameter_list: Node | None,
    source: bytes,
    macros: dict[bytes, tuple[ParameterMacro, ...]] | None = None,
) -> tuple[str, ...]:
    """
    Extract deterministic parameter names from one parameter list.

    Parameters
    ----------
    parameter_list : tree_sitter.Node | None
        Parameter list node from a function declarator.
    source : bytes
        Full source buffer.
    macros : dict[bytes, tuple[ParameterMacro, ...]] | None, optional
        Captured parameter identity alternatives and unsafe names.

    Returns
    -------
    tuple[str, ...]
        Parameter names in declaration order.
    """
    if parameter_list is None:
        return ()

    parameters: list[str] = []
    for child in parameter_list.named_children:
        if child.type != "parameter_declaration":
            continue
        recovered = macro_parameter_name(child, source, macros) if macros else None
        if recovered is not None:
            parameters.append(recovered)
            continue
        declarator = child.child_by_field_name("declarator")
        if declarator is None:
            continue
        name = _unwrap_declarator_name(declarator, source)
        if name is not None:
            parameters.append(name)
    return tuple(parameters)


def _find_parameter_list(node: Node | None) -> Node | None:
    """
    Find the parameter-list node nested inside one declarator tree.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Declarator subtree that may own a function declarator.

    Returns
    -------
    tree_sitter.Node | None
        Nested ``parameter_list`` node when present.
    """
    if node is None:
        return None
    if node.type == "parameter_list":
        return node

    parameter_list = node.child_by_field_name("parameters")
    if parameter_list is not None:
        return parameter_list

    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        nested = _find_parameter_list(declarator)
        if nested is not None:
            return nested

    for child in node.named_children:
        nested = _find_parameter_list(child)
        if nested is not None:
            return nested
    return None


def _is_supported_function_definition(node: Node) -> bool:
    """
    Decide whether one parsed function-definition node is semantically usable.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate top-level ``function_definition`` node.

    Returns
    -------
    bool
        ``True`` when the node exposes a callable declarator with parameters
        and contains no top-level parse error markers.
    """
    if any(child.type == "ERROR" for child in node.named_children):
        return False

    declarator = node.child_by_field_name("declarator")
    return _find_parameter_list(declarator) is not None


def _c_external_target_kind(target: str) -> str:
    """
    Classify one C call target for unresolved graph rendering.

    Parameters
    ----------
    target : str
        Call target token.

    Returns
    -------
    str
        Analyzer-owned external target classifier.
    """
    if target in _C_MACROS or target.isupper():
        return "C:<macro>"
    if target in _C_SYSTEM_FUNCTIONS:
        return "C:<system-header>"
    return "C:<external>"


def _call_site_from_expression(node: Node, source: bytes) -> CallSite | None:
    """
    Convert one tree-sitter call expression into a normalized call record.

    Parameters
    ----------
    node : tree_sitter.Node
        Call-expression node.
    source : bytes
        Full source buffer.

    Returns
    -------
    codira.models.CallSite | None
        Normalized call record, or ``None`` when no supported target exists.
    """
    if _is_complex_operator_call(node, source):
        return None
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return None

    if function_node.type == "identifier":
        target = _node_text(function_node, source)
        return CallSite(
            kind="name",
            target=target,
            lineno=function_node.start_point.row + 1,
            col_offset=function_node.start_point.column,
            external_target_kind=_c_external_target_kind(target),
            external_target_name=target,
        )

    if function_node.type == "field_expression":
        receiver = function_node.child_by_field_name("argument")
        field = function_node.child_by_field_name("field")
        if receiver is None or field is None:
            return None
        target = _node_text(field, source)
        return CallSite(
            kind="attribute",
            target=target,
            lineno=field.start_point.row + 1,
            col_offset=field.start_point.column,
            base=_node_text(receiver, source),
            external_target_kind="C:<external>",
            external_target_name=target,
        )

    return CallSite(
        kind="unresolved",
        target="",
        lineno=function_node.start_point.row + 1,
        col_offset=function_node.start_point.column,
    )


def _extract_calls(body: Node | None, source: bytes) -> tuple[CallSite, ...]:
    """
    Extract normalized calls from one function body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Compound-statement node owning the function body.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Call records in deterministic source order, including original macro
        invocations retained beside proven loop-prefix grammar projections.
    """
    if body is None:
        return ()

    calls: list[CallSite] = []
    for node in _named_descendants(body):
        call = None
        if node.type == "call_expression":
            call = _call_site_from_expression(node, source)
        else:
            macro = projected_statement_macro_name(node, source)
            if macro is not None:
                call = CallSite(
                    kind="name",
                    target=macro,
                    lineno=node.start_point.row + 1,
                    col_offset=node.start_point.column,
                    external_target_kind=_c_external_target_kind(macro),
                    external_target_name=macro,
                )
        if call is not None:
            calls.append(call)
    return tuple(calls)


def _returns_value(body: Node | None) -> int:
    """
    Detect whether one function body contains a value-returning statement.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Compound-statement node owning the function body.

    Returns
    -------
    int
        ``1`` when the body contains ``return <expr>;``, else ``0``.
    """
    if body is None:
        return 0

    for node in _named_descendants(body):
        if node.type == "return_statement" and len(node.named_children) > 0:
            return 1
    return 0


def _top_level_nodes(root: Node) -> Iterator[Node]:
    """Visit lexical file-scope nodes through conditional directive wrappers.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation unit whose function/type bodies remain opaque.

    Returns
    -------
    collections.abc.Iterator[tree_sitter.Node]
        Source-ordered nodes from all written conditional alternatives.
    """
    pending = list(reversed(root.children))
    while pending:
        node = pending.pop()
        yield node
        if node.type in {
            "preproc_if",
            "preproc_ifdef",
            "preproc_else",
            "preproc_elif",
            "preproc_elifdef",
        }:
            condition = node.child_by_field_name("condition")
            name = node.child_by_field_name("name")
            pending.extend(
                child
                for child in reversed(node.named_children)
                if child != condition and child != name
            )


def _function_declaration(node: Node) -> Node | None:
    """Follow a declared name's binding to distinguish functions from variables.

    Parameters
    ----------
    node : tree_sitter.Node
        File-scope declaration with an optional function declarator.

    Returns
    -------
    tree_sitter.Node | None
        Bound function declarator, excluding pointer and array variables.
    """
    current = node.child_by_field_name("declarator")
    function: Node | None = None
    while current is not None:
        if current.type == "function_declarator":
            function = current
        elif current.type in {"pointer_declarator", "array_declarator"}:
            function = None
        nested = current.child_by_field_name("declarator")
        if nested is None and current.type == "parenthesized_declarator":
            nested = next(iter(current.named_children), None)
        current = nested
    return function


def _extract_functions(
    root: Node,
    source: bytes,
    *,
    module_name: str,
    owner_id: str,
    macros: dict[bytes, tuple[ParameterMacro, ...]] | None = None,
) -> tuple[FunctionArtifact, ...]:
    """
    Extract C function definitions and otherwise unrepresented prototypes.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.
    module_name : str
        Dotted owner module name.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    macros : dict[bytes, tuple[ParameterMacro, ...]] | None, optional
        Captured parameter identity alternatives and unsafe names.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Deterministic function artifacts ordered by source position.
    """
    functions: list[FunctionArtifact] = []

    for child in _top_level_nodes(root):
        if child.type not in {"function_definition", "declaration"}:
            continue
        if not _is_supported_function_definition(child):
            continue
        declarator = (
            _function_declaration(child)
            if child.type == "declaration"
            else child.child_by_field_name("declarator")
        )
        body = child.child_by_field_name("body")
        if declarator is None:
            continue

        name = _unwrap_declarator_name(declarator, source)
        if name is None:
            continue

        parameter_list = _find_parameter_list(declarator)
        parameters = _extract_parameter_names(parameter_list, source, macros)
        signature_end = body.start_byte if body is not None else declarator.end_byte
        signature_start = _original_declaration_start(child, source)
        signature = _decode_source_text(source[signature_start:signature_end]).strip()
        is_public = int(
            not any(
                sub.type == "storage_class_specifier"
                and _node_text(sub, source) == "static"
                for sub in child.children
            )
        )

        functions.append(
            FunctionArtifact(
                name=name,
                stable_id=_function_stable_id(owner_id, name),
                lineno=child.start_point.row
                + 1
                - source.count(b"\n", signature_start, child.start_byte),
                end_lineno=body.end_point.row + 1 if body is not None else None,
                signature=" ".join(signature.split()),
                docstring=None,
                has_docstring=0,
                is_method=0,
                is_public=is_public,
                parameters=parameters,
                returns_value=_returns_value(body),
                yields_value=0,
                raises=0,
                has_asserts=0,
                decorators=(),
                calls=_extract_calls(body, source),
                callable_refs=(),
            )
        )

    defined = {fn.name for fn in functions if fn.end_lineno is not None}
    return _disambiguate_function_stable_ids(
        tuple(
            fn
            for fn in functions
            if fn.end_lineno is not None or fn.name not in defined
        )
    )


def _disambiguate_function_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Disambiguate duplicate C function stable IDs within one file analysis.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Extracted function artifacts in source order.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Function artifacts with duplicate stable IDs rewritten deterministically.
    """
    counts: dict[str, int] = {}
    for function in functions:
        counts[function.stable_id] = counts.get(function.stable_id, 0) + 1

    if all(count == 1 for count in counts.values()):
        return functions

    used_ids: set[str] = set()
    disambiguated: list[FunctionArtifact] = []
    for function in functions:
        stable_id = function.stable_id
        if counts[stable_id] > 1:
            digest = hashlib.sha256(function.signature.encode("utf-8")).hexdigest()[:12]
            stable_id = f"{stable_id}:{digest}"
            if stable_id in used_ids:
                stable_id = f"{stable_id}:{function.lineno}"
            function = replace(function, stable_id=stable_id)
        used_ids.add(stable_id)
        disambiguated.append(function)
    return tuple(disambiguated)


def _declaration_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the exposed declaration name for one top-level type node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration node being normalized.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Declaration name when one is present.
    """
    if node.type == "type_definition":
        alias_node = node.child_by_field_name("declarator")
        while alias_node is not None:
            if alias_node.type in {"type_identifier", "identifier", "primitive_type"}:
                return _node_text(alias_node, source)
            nested = alias_node.child_by_field_name("declarator")
            if nested is None and alias_node.type == "parenthesized_declarator":
                nested = next(iter(alias_node.named_children), None)
            alias_node = nested
        return None

    if node.type in {"preproc_def", "preproc_function_def"}:
        identifier = next(
            (child for child in node.named_children if child.type == "identifier"),
            None,
        )
        if identifier is None:
            return None
        return _node_text(identifier, source)

    for named_child in node.named_children:
        if named_child.type in {"type_identifier", "identifier"}:
            return _node_text(named_child, source)
    return None


def _resolve_declaration_docstring(
    attached_comments: dict[int, str],
    node: Node,
    inherited_comment: str | None = None,
) -> str | None:
    """
    Resolve the best docstring to attach to one declaration node.

    Parameters
    ----------
    attached_comments : dict[int, str]
        Leading comment summaries keyed by declaration start byte.
    node : tree_sitter.Node
        Declaration node whose docstring should be resolved.
    inherited_comment : str | None, optional
        Leading comment summary inherited from an owning declaration node.

    Returns
    -------
    str | None
        Attached comment when present, otherwise the inherited comment.
    """
    return attached_comments.get(node.start_byte, inherited_comment)


def _extract_enum_members(
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    enum_name: str,
    parent_stable_id: str,
) -> tuple[EnumMemberArtifact, ...]:
    """
    Extract deterministic enum members from one named enum declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        Enum-specifier node that owns the enumerator list.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    enum_name : str
        Owning enum declaration name.
    parent_stable_id : str
        Stable identity of the owning enum declaration artifact.

    Returns
    -------
    tuple[codira.models.EnumMemberArtifact, ...]
        Ordered enum-member artifacts attached to the enum declaration.
    """
    enumerator_list = next(
        (child for child in node.named_children if child.type == "enumerator_list"),
        None,
    )
    if enumerator_list is None:
        return ()

    members: list[EnumMemberArtifact] = []
    for ordinal, enumerator in enumerate(
        (
            child
            for child in enumerator_list.named_children
            if child.type == "enumerator"
        ),
        start=1,
    ):
        name = next(
            (
                _node_text(child, source)
                for child in enumerator.named_children
                if child.type in {"identifier", "field_identifier"}
            ),
            None,
        )
        if name is None:
            continue
        members.append(
            EnumMemberArtifact(
                stable_id=_enum_member_stable_id(owner_id, enum_name, ordinal),
                parent_stable_id=parent_stable_id,
                ordinal=ordinal,
                name=name,
                signature=" ".join(_node_text(enumerator, source).split()),
                lineno=enumerator.start_point.row + 1,
            )
        )
    return tuple(members)


def _declaration_artifact(
    node: Node,
    source: bytes,
    *,
    docstring: str | None,
    kind: DeclarationKind,
    owner_id: str,
) -> DeclarationArtifact | None:
    """
    Build one normalized declaration artifact when the node is named.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration node being normalized.
    source : bytes
        Full source buffer.
    docstring : str | None
        Docstring to attach to the declaration.
    kind : str
        Stable declaration classifier.
    owner_id : str
        File-scoped owner identity preserving the source suffix.

    Returns
    -------
    codira.models.DeclarationArtifact | None
        Normalized declaration artifact, or ``None`` when no usable name is
        present.
    """
    name = _declaration_name(node, source)
    if name is None:
        return None
    start = _original_declaration_start(node, source)
    return DeclarationArtifact(
        name=name,
        stable_id=_declaration_stable_id(owner_id, kind, name),
        kind=kind,
        lineno=source.count(b"\n", 0, start) + 1,
        signature=" ".join(_decode_source_text(source[start : node.end_byte]).split()),
        docstring=docstring,
        enum_members=(
            _extract_enum_members(
                node,
                source,
                owner_id=owner_id,
                enum_name=name,
                parent_stable_id=_declaration_stable_id(owner_id, kind, name),
            )
            if kind == "enum"
            else ()
        ),
    )


def _const_declaration_artifacts(
    node: Node,
    source: bytes,
    *,
    docstring: str | None,
    owner_id: str,
) -> tuple[DeclarationArtifact, ...]:
    """
    Build normalized C ``const`` declaration artifacts when accepted.

    Parameters
    ----------
    node : tree_sitter.Node
        Top-level declaration node being considered.
    source : bytes
        Full source buffer.
    docstring : str | None
        Docstring to attach to the declaration.
    owner_id : str
        File-scoped owner identity preserving the source suffix.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Normalized constant declarations owned by the accepted node.
    """
    if node.type != "declaration":
        return ()

    type_qualifiers = {
        _node_text(child, source)
        for child in node.named_children
        if child.type == "type_qualifier"
    }
    if "const" not in type_qualifiers:
        return ()

    declarators: list[Node] = []
    for child in node.named_children:
        if child.type == "init_declarator":
            declarator = child.child_by_field_name("declarator")
            if declarator is not None:
                declarators.append(declarator)
            continue
        if child.type in {
            "identifier",
            "pointer_declarator",
            "array_declarator",
            "parenthesized_declarator",
            "function_declarator",
        }:
            declarators.append(child)

    artifacts: list[DeclarationArtifact] = []
    for declarator in declarators:
        if _find_parameter_list(declarator) is not None:
            continue
        name = _unwrap_declarator_name(declarator, source)
        if name is None:
            continue
        artifacts.append(
            DeclarationArtifact(
                name=name,
                stable_id=_declaration_stable_id(owner_id, "constant", name),
                kind="constant",
                lineno=node.start_point.row + 1,
                signature=" ".join(_node_text(node, source).split()),
                docstring=docstring,
            )
        )

    return tuple(artifacts)


def _record_declaration(
    declarations_by_stable_id: dict[str, DeclarationArtifact],
    declaration: DeclarationArtifact | None,
) -> None:
    """
    Store one declaration artifact when it exists.

    Parameters
    ----------
    declarations_by_stable_id : dict[str, codira.models.DeclarationArtifact]
        Accumulator preserving typedef alternatives and other symbol identities.
    declaration : codira.models.DeclarationArtifact | None
        Declaration artifact to record.

    Returns
    -------
    None
        The declaration map is updated in place when a declaration exists.
    """
    if declaration is not None:
        key = declaration.stable_id
        if declaration.kind == "typedef":
            digest = hashlib.sha256(declaration.signature.encode()).hexdigest()[:12]
            key = f"{key}:{digest}:{declaration.lineno}"
        declarations_by_stable_id[key] = declaration


def _disambiguate_type_aliases(
    declarations: tuple[DeclarationArtifact, ...],
) -> tuple[DeclarationArtifact, ...]:
    """Give distinct written typedef alternatives unique normalized identities.

    Parameters
    ----------
    declarations : tuple[codira.models.DeclarationArtifact, ...]
        Source-ordered declarations, including conditional typedef variants.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Original single identities and signature/line identities for duplicates.
    """
    counts: dict[str, int] = {}
    for item in declarations:
        counts[item.stable_id] = counts.get(item.stable_id, 0) + 1
    return tuple(
        replace(
            item,
            stable_id=f"{item.stable_id}:{hashlib.sha256(item.signature.encode()).hexdigest()[:12]}:{item.lineno}",
        )
        if counts[item.stable_id] > 1
        else item
        for item in declarations
    )


def _record_nested_type_declarations(
    child: Node,
    source: bytes,
    *,
    attached_comments: dict[int, str],
    declarations_by_stable_id: dict[str, DeclarationArtifact],
    owner_id: str,
) -> None:
    """
    Record nested declarations found inside one C type-definition node.

    Parameters
    ----------
    child : tree_sitter.Node
        Type-definition node to inspect.
    source : bytes
        Full source buffer.
    attached_comments : dict[int, str]
        Comment blocks keyed by source byte offset.
    declarations_by_stable_id : dict[str, codira.models.DeclarationArtifact]
        Accumulator preserving typedef alternatives and other symbol identities.
    owner_id : str
        File-scoped owner identity preserving the source suffix.

    Returns
    -------
    None
        Matching nested declarations are added in place.
    """
    child_comment = attached_comments.get(child.start_byte)
    for named_child in child.named_children:
        if named_child.type == "struct_specifier":
            kind: DeclarationKind = "struct"
        elif named_child.type == "union_specifier":
            kind = "union"
        elif named_child.type == "enum_specifier":
            kind = "enum"
        else:
            continue
        declaration = _declaration_artifact(
            named_child,
            source,
            docstring=_resolve_declaration_docstring(
                attached_comments,
                named_child,
                inherited_comment=child_comment,
            ),
            kind=kind,
            owner_id=owner_id,
        )
        _record_declaration(declarations_by_stable_id, declaration)


def _record_member_type_declarations(
    child: Node,
    source: bytes,
    *,
    attached_comments: dict[int, str],
    declarations_by_stable_id: dict[str, DeclarationArtifact],
    owner_id: str,
) -> None:
    """
    Record written record/enum tags through declaration and member-type bindings.

    Parameters
    ----------
    child : tree_sitter.Node
        Record, enum, declaration or typedef node to inspect.
    source : bytes
        Full source buffer.
    attached_comments : dict[int, str]
        Comment blocks keyed by source byte offset.
    declarations_by_stable_id : dict[str, codira.models.DeclarationArtifact]
        Accumulator preserving typedef alternatives and other symbol identities.
    owner_id : str
        File-scoped owner identity preserving the source suffix.

    Returns
    -------
    None
        Named tags are added in place, including anonymous record containers.
        Function bodies, parameter types, initializers and field values are opaque.
    """
    pending = [(child, attached_comments.get(child.start_byte))]
    kinds: dict[str, DeclarationKind] = {
        "struct_specifier": "struct",
        "union_specifier": "union",
        "enum_specifier": "enum",
    }
    while pending:
        node, inherited_comment = pending.pop()
        kind = kinds.get(node.type)
        if kind is not None:
            _record_declaration(
                declarations_by_stable_id,
                _declaration_artifact(
                    node,
                    source,
                    docstring=_resolve_declaration_docstring(
                        attached_comments, node, inherited_comment=inherited_comment
                    ),
                    kind=kind,
                    owner_id=owner_id,
                ),
            )
            body = node.child_by_field_name("body")
            if body is not None and body.type == "field_declaration_list":
                comments = _attached_comment_map(body, source)
                pending.extend(
                    (field, comments.get(field.start_byte))
                    for field in reversed(tuple(_top_level_nodes(body)))
                )
        elif node.type in {"declaration", "field_declaration", "type_definition"}:
            declared_type = node.child_by_field_name("type")
            if (
                declared_type is not None
                and declared_type.type in kinds
                and (
                    node.type == "type_definition"
                    or declared_type.child_by_field_name("body") is not None
                )
            ):
                pending.append((declared_type, inherited_comment))


def _extract_declarations(
    root: Node,
    source: bytes,
    *,
    owner_id: str,
) -> tuple[DeclarationArtifact, ...]:
    """
    Extract file-scope declarations and absent member tags, preserving prior identities.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.

    Returns
    -------
    tuple[codira.models.DeclarationArtifact, ...]
        Deterministic declaration artifacts ordered by source position.
    """
    declarations_by_stable_id: dict[str, DeclarationArtifact] = {}
    attached_comments = _attached_comment_map(root, source)

    for child in _top_level_nodes(root):
        if child.type in {"preproc_def", "preproc_function_def"}:
            declaration = _declaration_artifact(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                kind="macro",
                owner_id=owner_id,
            )
            _record_declaration(declarations_by_stable_id, declaration)
            continue

        if child.type == "declaration":
            declarations = _const_declaration_artifacts(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                owner_id=owner_id,
            )
            for declaration in declarations:
                _record_declaration(declarations_by_stable_id, declaration)
            continue

        if child.type == "struct_specifier":
            declaration = _declaration_artifact(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                kind="struct",
                owner_id=owner_id,
            )
            _record_declaration(declarations_by_stable_id, declaration)
            continue

        if child.type == "union_specifier":
            declaration = _declaration_artifact(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                kind="union",
                owner_id=owner_id,
            )
            _record_declaration(declarations_by_stable_id, declaration)
            continue

        if child.type == "enum_specifier":
            declaration = _declaration_artifact(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                kind="enum",
                owner_id=owner_id,
            )
            _record_declaration(declarations_by_stable_id, declaration)
            continue

        if child.type == "type_definition":
            _record_nested_type_declarations(
                child,
                source,
                attached_comments=attached_comments,
                declarations_by_stable_id=declarations_by_stable_id,
                owner_id=owner_id,
            )
            declaration = _declaration_artifact(
                child,
                source,
                docstring=_resolve_declaration_docstring(attached_comments, child),
                kind="typedef",
                owner_id=owner_id,
            )
            _record_declaration(declarations_by_stable_id, declaration)

    additional: dict[str, DeclarationArtifact] = {}
    for child in _top_level_nodes(root):
        if child.type in {
            "declaration",
            "type_definition",
            "struct_specifier",
            "union_specifier",
            "enum_specifier",
        }:
            _record_member_type_declarations(
                child,
                source,
                attached_comments=attached_comments,
                declarations_by_stable_id=additional,
                owner_id=owner_id,
            )
    for stable_id, declaration in additional.items():
        declarations_by_stable_id.setdefault(stable_id, declaration)

    return _disambiguate_type_aliases(
        tuple(
            sorted(
                declarations_by_stable_id.values(),
                key=lambda artifact: artifact.lineno,
            )
        )
    )


def _documentation_artifact(
    *,
    path: Path,
    owner_stable_id: str,
    owner_kind: str,
    title: str,
    text: str,
    lineno: int,
    end_lineno: int | None,
    kind: DocumentationKind = "declaration",
) -> DocumentationArtifact:
    """
    Build one Doxygen documentation artifact for a C owner.

    Parameters
    ----------
    path : pathlib.Path
        Source file that owns the documentation artifact.
    owner_stable_id : str
        Stable identity of the documented owner.
    owner_kind : str
        Stable classifier of the documented owner.
    title : str
        Human-readable owner title.
    text : str
        Normalized Doxygen payload.
    lineno : int
        First Doxygen source line.
    end_lineno : int | None
        Inclusive final Doxygen source line when available.
    kind : str, optional
        Documentation artifact kind.

    Returns
    -------
    codira.models.DocumentationArtifact
        Normalized documentation artifact for retrieval.
    """
    return DocumentationArtifact(
        stable_id=f"doc:{kind}:{owner_stable_id}:doxygen",
        kind=kind,
        source_format="doxygen",
        source_path=path,
        lineno=lineno,
        end_lineno=end_lineno,
        title=title,
        heading_path=(),
        text=text,
        owner_stable_id=owner_stable_id,
        owner_kind=owner_kind,
        attachment_confidence="explicit",
    )


def _documentation_artifacts(
    *,
    path: Path,
    module: ModuleArtifact,
    module_doxygen: tuple[str, int, int | None] | None,
    functions: tuple[FunctionArtifact, ...],
    declarations: tuple[DeclarationArtifact, ...],
    attached_doxygen: dict[int, tuple[str, int, int | None]],
) -> tuple[DocumentationArtifact, ...]:
    """
    Build C Doxygen documentation artifacts for module and declaration owners.

    Parameters
    ----------
    path : pathlib.Path
        C source path being analyzed.
    module : codira.models.ModuleArtifact
        Module artifact owned by the source path.
    module_doxygen : tuple[str, int, int | None] | None
        Leading Doxygen module documentation and source coordinates.
    functions : tuple[codira.models.FunctionArtifact, ...]
        Function artifacts that may own Doxygen documentation.
    declarations : tuple[codira.models.DeclarationArtifact, ...]
        Declaration artifacts that may own Doxygen documentation.
    attached_doxygen : dict[int, tuple[str, int, int | None]]
        Attached Doxygen documentation keyed by owner declaration line.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        Deterministic Doxygen documentation artifacts.
    """
    artifacts: list[DocumentationArtifact] = []
    if module_doxygen is not None:
        text, lineno, end_lineno = module_doxygen
        artifacts.append(
            _documentation_artifact(
                path=path,
                owner_stable_id=module.stable_id,
                owner_kind="module",
                title=module.name,
                text=text,
                lineno=lineno,
                end_lineno=end_lineno,
                kind="module",
            )
        )

    for function in functions:
        attached = attached_doxygen.get(function.lineno)
        if attached is None:
            continue
        text, lineno, end_lineno = attached
        artifacts.append(
            _documentation_artifact(
                path=path,
                owner_stable_id=function.stable_id,
                owner_kind="function",
                title=function.name,
                text=text,
                lineno=lineno,
                end_lineno=end_lineno,
            )
        )

    for declaration in declarations:
        attached = attached_doxygen.get(declaration.lineno)
        if attached is None:
            continue
        text, lineno, end_lineno = attached
        artifacts.append(
            _documentation_artifact(
                path=path,
                owner_stable_id=declaration.stable_id,
                owner_kind=declaration.kind,
                title=declaration.name,
                text=text,
                lineno=lineno,
                end_lineno=end_lineno,
            )
        )

    return tuple(artifacts)


def _extract_imports(root: Node, source: bytes) -> tuple[ImportArtifact, ...]:
    """
    Extract include rows from one translation unit.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit root node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[codira.models.ImportArtifact, ...]
        Deterministic include rows ordered by source position.
    """
    imports: list[ImportArtifact] = []

    for child in _top_level_nodes(root):
        if child.type != "preproc_include":
            continue
        include_target = None
        include_kind: ImportKind = "include_local"
        for named_child in child.named_children:
            if named_child.type == "string_literal":
                include_target = _node_text(named_child, source).strip('"')
                include_kind = "include_local"
                break
            if named_child.type == "system_lib_string":
                include_target = _node_text(named_child, source).strip("<>")
                include_kind = "include_system"
                break
        if include_target is None:
            continue
        imports.append(
            ImportArtifact(
                name=include_target,
                alias=None,
                lineno=child.start_point.row + 1,
                kind=include_kind,
            )
        )

    return tuple(imports)


def _merge_c_views(analyses: list[AnalysisResult], owner_id: str) -> AnalysisResult:
    """Merge written alternatives without duplicating shared source artifacts.

    Parameters
    ----------
    analyses : list[codira.models.AnalysisResult]
        Fully clean views of one source file in deterministic covering order.
    owner_id : str
        Original source-owned identity prefix.

    Returns
    -------
    codira.models.AnalysisResult
        Source-ordered artifacts with unique variant identities and remapped docs.
    """
    functions: dict[tuple[str, int, int | None, str], FunctionArtifact] = {}
    declarations: dict[tuple[str, str, int, str], DeclarationArtifact] = {}
    for analysis in analyses:
        for function in analysis.functions:
            key = (
                function.name,
                function.lineno,
                function.end_lineno,
                function.signature,
            )
            previous = functions.get(key)
            if previous is not None:
                function = replace(
                    function,
                    calls=tuple(
                        sorted(
                            set(previous.calls) | set(function.calls),
                            key=lambda c: (
                                c.lineno,
                                c.col_offset,
                                c.kind,
                                c.base,
                                c.target,
                            ),
                        )
                    ),
                    returns_value=max(previous.returns_value, function.returns_value),
                )
            functions[key] = replace(
                function, stable_id=_function_stable_id(owner_id, function.name)
            )
        for declaration in analysis.declarations:
            key_decl = (
                declaration.kind,
                declaration.name,
                declaration.lineno,
                declaration.signature,
            )
            declarations[key_decl] = replace(
                declaration,
                stable_id=_declaration_stable_id(
                    owner_id, declaration.kind, declaration.name
                ),
            )
    final_functions = _disambiguate_function_stable_ids(
        tuple(sorted(functions.values(), key=lambda f: (f.lineno, f.name, f.signature)))
    )
    final_declarations = _disambiguate_type_aliases(
        tuple(sorted(declarations.values(), key=lambda d: (d.lineno, d.name, d.kind)))
    )
    function_ids = {
        (f.name, f.lineno, f.end_lineno, f.signature): f.stable_id
        for f in final_functions
    }
    declaration_ids = {
        (d.kind, d.name, d.lineno, d.signature): d.stable_id for d in final_declarations
    }
    documents: dict[str, DocumentationArtifact] = {}
    imports: dict[tuple[int, str, str, str | None], ImportArtifact] = {}
    for analysis in analyses:
        owners = {
            f.stable_id: function_ids[(f.name, f.lineno, f.end_lineno, f.signature)]
            for f in analysis.functions
        }
        owners.update(
            {
                d.stable_id: declaration_ids[(d.kind, d.name, d.lineno, d.signature)]
                for d in analysis.declarations
            }
        )
        for document in analysis.documentation:
            if (
                document.owner_stable_id is not None
                and document.owner_stable_id in owners
            ):
                owner = owners[document.owner_stable_id]
                document = replace(
                    document,
                    owner_stable_id=owner,
                    stable_id=f"doc:{document.kind}:{owner}:doxygen",
                )
            documents[document.stable_id] = document
        for item in analysis.imports:
            imports[(item.lineno, item.name, item.kind, item.alias)] = item
    return replace(
        analyses[0],
        functions=final_functions,
        declarations=final_declarations,
        imports=tuple(
            sorted(imports.values(), key=lambda item: (item.lineno, item.name))
        ),
        documentation=tuple(
            sorted(documents.values(), key=lambda item: (item.lineno, item.stable_id))
        ),
    )


def _blank_expansions(
    source: bytes, expansions: tuple[ExpandedDeclaration, ...]
) -> bytes:
    """Blank only completely proven invocation spans without shifting offsets.

    Parameters
    ----------
    source : bytes
        Original translation unit.
    expansions : tuple[ExpandedDeclaration, ...]
        Fully selected expansion records.

    Returns
    -------
    bytes
        Coordinate preserving source projection.
    """
    projected = bytearray(source)
    for expansion in expansions:
        site_end = expansion.end
        while site_end < len(source) and source[site_end] in b" \t\r\n":
            site_end += 1
        if site_end < len(source) and source[site_end : site_end + 1] == b";":
            site_end += 1
        for offset in range(expansion.start, site_end):
            if projected[offset] not in (10, 13):
                projected[offset] = 32
    return bytes(projected)


def _analysis_context_identity(identity: str, configuration: str) -> str:
    """Add the active C configuration to a captured include identity.

    Parameters
    ----------
    identity : str
        Canonical include-context identity JSON.
    configuration : str
        Analyzer configuration fingerprint.

    Returns
    -------
    str
        Canonical generated-provenance context identity.
    """
    payload = json.loads(identity)
    payload["configuration_fingerprint"] = configuration
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _expanded_functions(
    expansion: ExpandedDeclaration,
    *,
    path: Path,
    root: Path,
    source: bytes,
    included_sources: tuple[tuple[bytes, int], ...],
    context_identity: str,
    module_name: str,
    owner_id: str,
) -> tuple[FunctionArtifact, ...]:
    """Extract generated callable declarations with invocation anchored evidence.

    Parameters
    ----------
    expansion : ExpandedDeclaration
        Fully expanded declaration macro and selected definition chain.
    path : pathlib.Path
        Original source path.
    root : pathlib.Path
        Repository root used for module ownership.
    source : bytes
        Original translation unit.
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers available at the original invocation boundary.
    context_identity : str
        Configuration and exact include-context identity.
    module_name : str
        Dotted module name for source-owned artifacts.
    owner_id : str
        Stable file owner identity.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Generated prototypes and definitions represented by the existing model.

    Raises
    ------
    ValueError
        If the generated token stream is malformed or contains unmodeled types.
    """
    parser = _new_parser()
    parsed = _parse_c_source(expansion.source, parser, included_sources)
    if parsed.has_error:
        raise ValueError("generated declaration does not parse completely")
    top_level = tuple(node for node in parsed.named_children if node.type != "comment")
    if any(
        node.type not in {"function_definition", "declaration"} for node in top_level
    ):
        raise ValueError("generated expansion contains an unsupported top-level node")
    modeled_declarations = _extract_declarations(
        parsed, expansion.source, owner_id=owner_id
    )
    if modeled_declarations:
        raise ValueError("generated expansion contains an unmodeled type or constant")
    for node in top_level:
        if node.type != "declaration":
            continue
        declarators = node.children_by_field_name("declarator")
        if len(declarators) == 1 and _function_declaration(node) is not None:
            continue
        if any(child.type == "call_expression" for child in _named_descendants(node)):
            raise ValueError("unmodeled generated declaration contains a call")
    line = source.count(b"\n", 0, expansion.start) + 1
    previous_newline = source.rfind(b"\n", 0, expansion.start)
    column = expansion.start - previous_newline - 1
    source_digest = hashlib.sha256(source).hexdigest()
    token_provenance = tuple(
        GeneratedTokenProvenance(
            spelling.decode("utf-8", "surrogateescape"),
            physical_span
            if physical_span is not None
            else (expansion.start, expansion.end),
            physical_span,
            "source" if physical_span is not None else "replacement",
        )
        for spelling, physical_span, _generated_span in expansion.tokens
    )
    input_provenance = tuple(
        MacroInputProvenance(
            name=item.name.decode("ascii"),
            replacement_sha256=item.replacement_sha256,
            source_path=(
                path.relative_to(root).as_posix()
                if item.source_path == "@source"
                else item.source_path
            ),
            source_sha256=(
                source_digest if item.source_path == "@source" else item.source_sha256
            ),
            span=item.span,
        )
        for item in expansion.definitions
    )
    functions: list[FunctionArtifact] = []
    for node in parsed.named_children:
        if node.type not in {"function_definition", "declaration"}:
            continue
        if node.type == "declaration" and _function_declaration(node) is None:
            continue
        node_source = expansion.source[node.start_byte : node.end_byte]
        node_tree = _parse_c_source(node_source, parser, included_sources)
        artifacts = _extract_functions(
            node_tree,
            node_source,
            module_name=module_name,
            owner_id=owner_id,
        )
        if len(artifacts) != 1:
            continue
        function = artifacts[0]
        role: Literal["definition", "prototype"] = (
            "definition" if node.type == "function_definition" else "prototype"
        )
        parameter_list = _find_parameter_list(node.child_by_field_name("declarator"))
        parameter_rows: list[tuple[str | None, str]] = []
        for parameter in parameter_list.named_children if parameter_list else ():
            if parameter.type != "parameter_declaration":
                if parameter.type == "comment":
                    continue
                raise ValueError("generated callable has unsupported parameter syntax")
            raw = expansion.source[parameter.start_byte : parameter.end_byte]
            declarator = parameter.child_by_field_name("declarator")
            name_node = _parameter_declarator_name(declarator)
            parameter_name = (
                None if name_node is None else _node_text(name_node, expansion.source)
            )
            if name_node is not None:
                first = name_node.start_byte - parameter.start_byte
                last = name_node.end_byte - parameter.start_byte
                raw = raw[:first] + raw[last:]
            parameter_type = " ".join(_decode_source_text(raw).split())
            parameter_rows.append((parameter_name, parameter_type))
        if len(parameter_rows) == 1 and parameter_rows[0][1] == "void":
            parameter_rows.clear()
        parameter_names = tuple(name for name, _ in parameter_rows)
        parameter_types = tuple(type_name for _, type_name in parameter_rows)
        generated = GeneratedCallableProvenance(
            role=role,
            invocation_span=(expansion.start, expansion.end),
            source_sha256=source_digest,
            context_identity=context_identity,
            tokens=token_provenance,
            inputs=input_provenance,
            parameter_names=parameter_names,
            parameter_types=parameter_types,
        )
        calls = tuple(
            _anchor_generated_call(
                call,
                node_start=node.start_byte,
                source=source,
                expansion=expansion,
                invocation=(line, column),
            )
            for call in function.calls
        )
        functions.append(
            replace(
                function,
                stable_id=_function_stable_id(owner_id, function.name),
                lineno=line,
                end_lineno=line if role == "definition" else None,
                calls=calls,
                generated=generated,
            )
        )
    represented = [
        child
        for child in top_level
        if child.type == "function_definition"
        or (child.type == "declaration" and _function_declaration(child) is not None)
    ]
    if len(functions) != len(represented):
        raise ValueError("generated callable could not be represented completely")
    if not functions:
        raise ValueError("expansion has no represented generated callable")
    by_name: dict[str, list[FunctionArtifact]] = {}
    for function in functions:
        by_name.setdefault(function.name, []).append(function)
    selected: list[FunctionArtifact] = []
    for declarations in by_name.values():
        definitions = [
            function
            for function in declarations
            if function.generated is not None
            and function.generated.role == "definition"
        ]
        prototypes = [
            function
            for function in declarations
            if function.generated is not None and function.generated.role == "prototype"
        ]
        if len({function.signature for function in definitions}) > 1:
            raise ValueError("generated definitions have conflicting signatures")
        if not definitions and len({function.signature for function in prototypes}) > 1:
            raise ValueError("generated prototypes have conflicting signatures")
        selected.append((definitions or prototypes)[0])
    return tuple(selected)


def _parameter_declarator_name(node: Node | None) -> Node | None:
    """Locate the identifier belonging to a parameter declarator.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Parameter declarator, when it has a name.

    Returns
    -------
    tree_sitter.Node | None
        Exact identifier node, excluding nested parameter identifiers.
    """
    if node is None:
        return None
    if node.type in {"identifier", "field_identifier"}:
        return node
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        return _parameter_declarator_name(declarator)
    for child in node.named_children:
        found = _parameter_declarator_name(child)
        if found is not None:
            return found
    return None


def _anchor_generated_call(
    call: CallSite,
    *,
    node_start: int,
    source: bytes,
    expansion: ExpandedDeclaration,
    invocation: tuple[int, int],
) -> CallSite:
    """Map a generated call to its source argument or invocation anchor.

    Parameters
    ----------
    call : codira.models.CallSite
        Call extracted from an isolated generated declaration.
    node_start : int
        Generated-buffer start of the containing callable node.
    source : bytes
        Original physical translation unit.
    expansion : ExpandedDeclaration
        Generated token and source-origin mapping.
    invocation : tuple[int, int]
        Original invocation line and byte column.

    Returns
    -------
    codira.models.CallSite
        Call with a physical argument coordinate when its target token came
        from an argument, otherwise the original invocation coordinate.
    """
    generated_line_start = node_start
    for _ in range(call.lineno - 1):
        newline = expansion.source.find(b"\n", generated_line_start)
        if newline < 0:
            generated_line_start = -1
            break
        generated_line_start = newline + 1
    generated_position = (
        -1 if generated_line_start < 0 else generated_line_start + call.col_offset
    )
    physical = next(
        (
            physical_span
            for _, physical_span, generated_span in expansion.tokens
            if generated_span[0] == generated_position
        ),
        None,
    )
    if physical is None:
        return replace(call, lineno=invocation[0], col_offset=invocation[1])
    start = physical[0]
    line = source.count(b"\n", 0, start) + 1
    previous_newline = source.rfind(b"\n", 0, start)
    return replace(call, lineno=line, col_offset=start - previous_newline - 1)


class CAnalyzer:
    """
    Concrete C analyzer for repository indexing.

    Parameters
    ----------
    None

    Notes
    -----
    This analyzer is backed by ``tree-sitter-c`` so further C extraction work
    can evolve from a real parse tree instead of regex heuristics.
    """

    name = "c"
    version = "21"
    discovery_globs: tuple[str, ...] = ("*.c", "*.h")
    default_coverage_roots: tuple[str, ...] = ("src", "include", "tests")

    def __init__(self) -> None:
        """Initialize independent options and explicit C input context.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Stores default options without reading repository inputs.
        """
        self._include_search_paths: tuple[Path, ...] = ()
        self._preinclude_headers: tuple[Path, ...] = ()
        self._path_filters = AnalyzerPathFilters()
        self._use_leading_comments = True
        self._emit_doxygen_documentation = True
        self._include_system_includes = True
        self._emit_macros = True
        self._expand_declaration_macros = False
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the C analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for C analyzer options.
        """

        return analyzer_json_schema(
            {
                "use_leading_comments": boolean_property(True),
                "emit_doxygen_documentation": boolean_property(True),
                "include_system_includes": boolean_property(True),
                "emit_macros": boolean_property(True),
                "expand_declaration_macros": {
                    **boolean_property(False),
                    "description": "Expand fully proven bounded file-scope declaration macros from captured source and contained headers; unsupported or uncertain sites remain partial.",
                },
                "include_search_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                    "description": "Ordered contained include search roots; quoted includes first search their own directory.",
                },
                "preinclude_headers": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                    "description": "Explicit contained caller-context headers whose definitions are available before the source begins.",
                },
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply C analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.

        Raises
        ------
        ValueError
            If include-search, caller-context or expansion options are malformed.
        """

        search_paths = config.get("include_search_paths", [])
        preinclude = config.get("preinclude_headers", [])
        expand_declaration_macros = config.get("expand_declaration_macros", False)
        if type(expand_declaration_macros) is not bool:
            raise ValueError("expand_declaration_macros must be a boolean")
        for option, value in (
            ("include_search_paths", search_paths),
            ("preinclude_headers", preinclude),
        ):
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise ValueError(f"{option} must be a list of nonempty strings")
        assert isinstance(search_paths, list) and isinstance(preinclude, list)
        self._include_search_paths = tuple(Path(item) for item in search_paths)
        self._preinclude_headers = tuple(Path(item) for item in preinclude)
        self._path_filters = analyzer_path_filters_from_config(config)
        self._use_leading_comments = bool(config.get("use_leading_comments", True))
        self._emit_doxygen_documentation = bool(
            config.get("emit_doxygen_documentation", True)
        )
        self._include_system_includes = bool(
            config.get("include_system_includes", True)
        )
        self._emit_macros = bool(config.get("emit_macros", True))
        self._expand_declaration_macros = expand_declaration_macros
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return C analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from C artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_c:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "documentation",
            ),
            does_not_support=("variable", "namespace"),
            mappings={
                "module": "module",
                "function": "callable",
                "constant": "constant",
                "macro": "constant",
                "struct": "type",
                "union": "type",
                "enum": "type",
                "typedef": "type",
                "include_local": "import",
                "include_system": "import",
                "doxygen": "documentation",
            },
        )

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """
        Return analyzer execution-safety guarantees.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Declaration permitting isolated process and thread workers.
        """

        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a C-family source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file is a ``.c`` or ``.h`` source file.
        """
        return path.suffix in _C_SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported C path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the path is allowed by include/exclude filters.
        """

        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analysis_input_fingerprint(self, path: Path, root: Path) -> str:
        """Bind analysis reuse to contained C header bytes and lookup outcomes.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit considered for analysis.
        root : pathlib.Path
            Repository boundary for all captured dependencies.

        Returns
        -------
        str
            Versioned source/header identity with configuration fingerprint.

        Raises
        ------
        ValueError
            If the source or explicit input paths escape the repository.
        OSError
            If the source or an explicitly required context header is unavailable.
        """
        context = read_include_context(
            path,
            root,
            include_paths=self._include_search_paths,
            preinclude_headers=self._preinclude_headers,
        )
        payload = json.loads(context.identity)
        payload["configuration_fingerprint"] = self.configuration_fingerprint
        return validate_analysis_input_fingerprint(
            json.dumps(
                payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")
            )
        )

    def analysis_input_fingerprint_matches(
        self, path: Path, root: Path, expected: str
    ) -> bool:
        """Recheck source, headers and resolutions without reparsing C syntax.

        Parameters
        ----------
        path : pathlib.Path
            Original translation unit.
        root : pathlib.Path
            Repository boundary for contained input validation.
        expected : str
            Previously captured versioned dependency identity.

        Returns
        -------
        bool
            Whether exact bytes, search roots, context headers and lookups match.
        """
        try:
            payload = json.loads(expected)
        except ValueError:
            return False
        return (
            isinstance(payload, dict)
            and payload.get("configuration_fingerprint")
            == self.configuration_fingerprint
            and include_identity_matches(
                path,
                root,
                expected,
                include_paths=self._include_search_paths,
                preinclude_headers=self._preinclude_headers,
            )
        )

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one C-family source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            C-family source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        context = read_include_context(
            path,
            root,
            include_paths=self._include_search_paths,
            preinclude_headers=self._preinclude_headers,
        )
        source = context.source
        included_sources = tuple(
            (header.source, header.available_after) for header in context.headers
        )
        parser = _new_parser()
        parse_projection = project_empty_function_macro_arguments(context, root, path)
        base = _parse_c_source(
            source, parser, included_sources, parse_projection=parse_projection
        )
        expansion_rejection: ExpansionRejected | None = None
        try:
            candidates = (
                declaration_expansions(context, root, path)
                if self._expand_declaration_macros
                else ()
            )
        except ExpansionRejected as exc:
            # A bounded expansion failure must leave the original parse result
            # intact. In particular, keep its recovery status and diagnostics
            # instead of exposing an internal exception or implying that the
            # generated declarations were analyzed.
            candidates = ()
            expansion_rejection = exc
        context_identity = _analysis_context_identity(
            context.identity, self.configuration_fingerprint
        )
        generated_by_expansion: dict[tuple[int, int], tuple[FunctionArtifact, ...]] = {}
        accepted: list[ExpandedDeclaration] = []
        for expansion in candidates:
            try:
                generated_by_expansion[(expansion.start, expansion.end)] = (
                    _expanded_functions(
                        expansion,
                        path=path,
                        root=root,
                        source=source,
                        included_sources=tuple(
                            (header.source, 0)
                            for header in context.headers
                            if header.available_after <= expansion.start
                        ),
                        context_identity=context_identity,
                        module_name=_module_name_for_path(path, root),
                        owner_id=_symbol_owner_id(path, root),
                    )
                )
            except ValueError:
                continue
            accepted.append(expansion)
        expansions = tuple(accepted)
        analysis_source = _blank_expansions(source, expansions)
        if analysis_source != source:
            base = _parse_c_source(analysis_source, parser, included_sources)
        macros = parameter_macros(source, included_sources)
        analyses: list[AnalysisResult] = []
        for view in c_parse_views(
            analysis_source, parser, base=base, included_sources=included_sources
        ):
            if view.root.has_error:
                analyses = [
                    self._analyze_view(
                        path,
                        root,
                        CParseView(analysis_source, base),
                        _parse_c_source(source, parser, included_sources),
                        macros,
                    )
                ]
                break
            analyses.append(self._analyze_view(path, root, view, base, macros))
        result = (
            analyses[0]
            if len(analyses) == 1
            else _merge_c_views(analyses, _symbol_owner_id(path, root))
        )
        if expansions:
            generated = tuple(
                function
                for expansion in expansions
                for function in generated_by_expansion[(expansion.start, expansion.end)]
            )
            result = replace(
                result,
                functions=_disambiguate_function_stable_ids(
                    tuple(
                        sorted(
                            (*result.functions, *generated),
                            key=lambda item: (item.lineno, item.name, item.signature),
                        )
                    )
                ),
            )
        if expansion_rejection is not None:
            status = result.status or AnalysisStatus(
                grammar="tree-sitter-c",
                target_contract={"language": "c"},
            )
            result = replace(
                result,
                index_symbols=False,
                status=replace(
                    status,
                    diagnostics=(
                        *status.diagnostics,
                        AnalysisDiagnostic(
                            category="declaration_macro_expansion",
                            message=(
                                "Declaration macro expansion was not completed: "
                                f"{expansion_rejection}"
                            ),
                        ),
                    ),
                    reliable_categories=(),
                    omitted_categories=(
                        "module",
                        "class",
                        "function",
                        "declaration",
                        "import",
                        "documentation",
                    ),
                    coverage_state=AnalysisCoverageState.PARTIAL,
                ),
            )
        return result

    def _analyze_view(
        self,
        path: Path,
        root: Path,
        view: CParseView,
        module_root: Node,
        macros: dict[bytes, tuple[ParameterMacro, ...]],
    ) -> AnalysisResult:
        """Build normalized artifacts for one validated source view.

        Parameters
        ----------
        path : pathlib.Path
            Original source path.
        root : pathlib.Path
            Repository boundary for identities.
        view : CParseView
            Coordinate-preserving signature source and parsed tree.
        module_root : tree_sitter.Node
            Original base tree for stable module documentation provenance.
        macros : dict[bytes, tuple[ParameterMacro, ...]]
            Captured parameter identity alternatives and unsafe names.

        Returns
        -------
        codira.models.AnalysisResult
            Source-owned artifacts for this view only.
        """
        source, root_node = view.source, view.root
        module_comment = (
            _leading_module_comment(module_root, source)
            if self._use_leading_comments
            else None
        )
        module_doxygen = _leading_module_doxygen(module_root, source)
        module_name = _module_name_for_path(path, root)
        owner_id = _symbol_owner_id(path, root)
        module = ModuleArtifact(
            name=module_name,
            stable_id=_module_stable_id(path, root),
            docstring=module_comment,
            has_docstring=int(module_comment is not None),
        )
        functions = _extract_functions(
            root_node,
            source,
            module_name=module_name,
            owner_id=owner_id,
            macros=macros,
        )
        declarations = _extract_declarations(
            root_node,
            source,
            owner_id=owner_id,
        )
        if not self._use_leading_comments:
            functions = tuple(
                replace(function, docstring=None) for function in functions
            )
            declarations = tuple(
                replace(declaration, docstring=None) for declaration in declarations
            )
        if not self._emit_macros:
            declarations = tuple(
                declaration
                for declaration in declarations
                if declaration.kind != "macro"
            )
        imports = _extract_imports(root_node, source)
        if not self._include_system_includes:
            imports = tuple(item for item in imports if item.kind != "include_system")
        return AnalysisResult(
            source_path=path,
            module=module,
            classes=(),
            functions=functions,
            declarations=declarations,
            imports=imports,
            documentation=(
                _documentation_artifacts(
                    path=path,
                    module=module,
                    module_doxygen=module_doxygen,
                    functions=functions,
                    declarations=declarations,
                    attached_doxygen=_attached_doxygen_comment_map(root_node, source),
                )
                if self._emit_doxygen_documentation
                else ()
            ),
            index_symbols=not root_node.has_error,
            status=tree_sitter_recovery_status(
                language="c", has_error=root_node.has_error
            ),
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party C analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        First-party C analyzer instance.
    """
    return CAnalyzer()
