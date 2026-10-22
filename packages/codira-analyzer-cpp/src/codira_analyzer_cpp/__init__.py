"""C++ language analyzer backed by tree-sitter.

Responsibilities
----------------
- Initialize the tree-sitter C++ parser and derive durable symbol identities.
- Walk C++ parse trees to extract namespaces, classes, callables, declarations,
  and imports deterministically.
- Translate the collected metadata into `AnalysisResult` objects for
  persistence.

Design principles
-----------------
The analyzer keeps C++-specific parsing isolated to this package so the core
runtime continues to own orchestration, storage, and query behavior.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the
first-party C++ analysis path for the Phase 2 multi-language expansion.
Parameters
----------
None

Returns
-------
None
    Defines the orchestration or plugin interfaces described above.
"""

from __future__ import annotations

import re

import hashlib
import json
from bisect import bisect_right
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from codira.contracts import LanguageAnalyzer
    from .cpp_macro_expansion import _MacroDefinition

from .cpp_namespace_bindings import (
    _namespace_bindings_from_config,
    _parse_with_namespace_bindings,
)
from .cpp_projection import SyntaxNode as Node, _ProjectedNode
from .cpp_preprocessor_queries import (
    FeatureAnswers,
    HeaderQuerySet,
    feature_answers,
    header_query_sets,
    header_queries_schema,
)

from .cpp_typedefs import _typedef_name_nodes
from .cpp_syntax import (
    _canonical_node_text,
    _class_stable_id,
    _conditional_children,
    _cpp_external_target_kind,
    _decode_source_text,
    _declaration_stable_id,
    _enum_member_stable_id,
    _function_stable_id,
    _module_name_for_path,
    _module_stable_id,
    _new_parser,
    _node_text,
    _normalize_signature,
    _qualified_name,
    _split_qualified_name,
    _symbol_owner_id,
)

from .cpp_comments import (
    CommentMaps,
    _attached_comment_map,
    _attached_doxygen_comment_map,
    _leading_module_comment,
    _leading_module_doxygen,
    source_comment_maps,
)

from .cpp_documentation import _documentation_artifacts
from .cpp_imports import _extract_imports
from .cpp_headers import has_named_template_parameters
from .cpp_include_context import (
    IncludeContext,
    include_identity_matches,
    read_include_context,
)
from .cpp_preprocessing import (
    _is_complex_operator_call,
    _original_declaration_start,
    _parse_cpp_source,
)

from codira.analysis_inputs import validate_analysis_input_fingerprint
from codira.contracts import (
    AnalyzerCapabilityDeclaration,
    AnalyzerConcurrencyDeclaration,
)
from codira.models import (
    AnalysisResult,
    AnalysisDiagnostic,
    AnalysisStatus,
    AnalysisCoverageState,
    CallSite,
    ClassArtifact,
    DeclarationArtifact,
    DeclarationKind,
    EnumMemberArtifact,
    FunctionArtifact,
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

_CPP_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".h"}
__all__ = ["CppAnalyzer", "_disambiguate_callable_stable_ids", "build_analyzer"]
_TYPE_LIKE_NAMES = {
    "auto",
    "bool",
    "char",
    "char16_t",
    "char32_t",
    "double",
    "float",
    "int",
    "long",
    "short",
    "size_t",
    "signed",
    "std",
    "uint8_t",
    "uint16_t",
    "uint32_t",
    "uint64_t",
    "int8_t",
    "int16_t",
    "int32_t",
    "int64_t",
    "unsigned",
    "void",
    "wchar_t",
}


@dataclass(frozen=True)
class _PendingFunction:
    """Hold a callable candidate awaiting ownership and redeclaration merging.

    Parameters
    ----------
    artifact : codira.models.FunctionArtifact
        Original-source callable artifacts.
    class_name : str | None
        Known class-like owner, if any.
    is_definition : bool
        Whether the candidate has a body or an explicit default/delete definition.
    binding_key : tuple[str, ...]
        Source-syntax parameter types and cv/ref/constraint qualifiers. Parameter
        names and default values do not distinguish redeclarations. Conditional
        branch identity keeps alternative source definitions separate.

    Returns
    -------
    None
        Initializes an immutable candidate.
    """

    artifact: FunctionArtifact
    class_name: str | None
    is_definition: bool
    binding_key: tuple[str, ...]


@dataclass
class _ClassBuilder:
    """Mutable accumulator for one class artifact before finalization."""

    qualified_name: str
    stable_id: str
    lineno: int
    end_lineno: int | None
    docstring: str | None
    has_docstring: int
    methods_by_key: dict[tuple[str, tuple[str, ...]], _PendingFunction] = field(
        default_factory=dict
    )

    def absorb_metadata(
        self,
        *,
        lineno: int,
        end_lineno: int | None,
        docstring: str | None,
    ) -> None:
        """
        Merge class metadata from a declaration or synthesized owner.

        Parameters
        ----------
        lineno : int
            Candidate starting line for the class artifact.
        end_lineno : int | None
            Candidate ending line for the class artifact.
        docstring : str | None
            Candidate class docstring from an attached comment.

        Returns
        -------
        None
            The stored class metadata is updated in place when the new values are
            richer.
        """
        if lineno < self.lineno:
            self.lineno = lineno
        if self.end_lineno is None and end_lineno is not None:
            self.end_lineno = end_lineno
        if self.docstring is None and docstring is not None:
            self.docstring = docstring
            self.has_docstring = 1

    def record_method(self, pending: _PendingFunction) -> None:
        """
        Record one method candidate for the class.

        Parameters
        ----------
        pending : _PendingFunction
            Method candidate to store.

        Returns
        -------
        None
            The method map is updated in place.
        """
        key = (pending.artifact.stable_id, pending.binding_key)
        current = self.methods_by_key.get(key)
        if current is None or _prefer_pending_function(current, pending) is pending:
            self.methods_by_key[key] = pending

    def build(self) -> ClassArtifact:
        """
        Finalize the immutable class artifact.

        Parameters
        ----------
        None

        Returns
        -------
        codira.models.ClassArtifact
            Class artifact with deterministically ordered methods.
        """
        methods = tuple(
            pending.artifact
            for pending in sorted(
                self.methods_by_key.values(),
                key=lambda item: (
                    item.artifact.lineno,
                    item.artifact.name,
                    item.artifact.signature,
                ),
            )
        )
        methods = _disambiguate_callable_stable_ids(methods)
        return ClassArtifact(
            name=self.qualified_name,
            stable_id=self.stable_id,
            lineno=self.lineno,
            end_lineno=self.end_lineno,
            docstring=self.docstring,
            has_docstring=self.has_docstring,
            methods=methods,
        )


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
    stack: list[Node] = [*node.named_children]
    stack.reverse()
    while stack:
        current = stack.pop()
        descendants.append(current)
        stack.extend(reversed(current.named_children))
    return descendants


def _template_inner_node(node: Node) -> Node | None:
    """
    Return the wrapped declaration inside one template declaration.

    Parameters
    ----------
    node : tree_sitter.Node
        `template_declaration` node.

    Returns
    -------
    tree_sitter.Node | None
        Wrapped declaration node when present.
    """
    children: list[Node] = [*node.named_children]
    for child in reversed(children):
        if child.type != "template_parameter_list":
            return child
    return None


def _namespace_parts(node: Node, source: bytes) -> tuple[str, ...]:
    """
    Resolve the namespace path declared by one namespace-definition node.

    Parameters
    ----------
    node : tree_sitter.Node
        `namespace_definition` node.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, ...]
        Namespace path components in declaration order. An unnamed namespace
        uses an explicit component to avoid collisions with its enclosing scope.
    """
    for child in node.named_children:
        if child.type in {"namespace_identifier", "nested_namespace_specifier"}:
            return _split_qualified_name(
                child.syntax_text.decode("utf-8", errors="replace")
                if isinstance(child, _ProjectedNode)
                else _node_text(child, source)
            )
    return ("(anonymous namespace)",)


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
        Nested `parameter_list` node when present.
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
        if named_child.type in {
            "identifier",
            "type_identifier",
            "field_identifier",
            "namespace_identifier",
        }:
            return _node_text(named_child, source)
    return None


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


def _looks_like_macro_or_type_name(name: str) -> bool:
    """
    Decide whether one declarator token looks like a macro or type name.

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


def _error_identifier_name(node: Node, source: bytes) -> str | None:
    """
    Extract one identifier-like token from an `ERROR` child when present.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may include a parse-error placeholder.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Recovered identifier text when the `ERROR` child looks usable.
    """
    for named_child in node.named_children:
        if named_child.type != "ERROR":
            continue
        text = _node_text(named_child, source).strip()
        if not text:
            continue
        if "(" in text or ")" in text or "[" in text or "]" in text:
            continue
        if not (text[0].isalpha() or text[0] in {"_", "~"}):
            continue
        if any(not (char.isalnum() or char in {"_", ":", "~"}) for char in text):
            continue
        return text
    return None


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
    for named_child in reversed([*node.named_children]):
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
    if direct_declarator is not None and direct_declarator.type in {
        "identifier",
        "field_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
    }:
        direct_name = _canonical_node_text(direct_declarator, source)
        error_name = _error_identifier_name(node, source)
        if error_name is not None and _looks_like_macro_or_type_name(direct_name):
            return error_name
        return direct_name

    macro_wrapped_name = _function_macro_wrapper_name(node, source)
    if macro_wrapped_name is not None:
        return macro_wrapped_name

    if direct_declarator is None or direct_declarator.type != "identifier":
        return None
    if not _looks_like_annotation_macro_name(_node_text(direct_declarator, source)):
        return None
    return _annotated_function_call_name(node, source)


def _unwrap_declarator_name(node: Node, source: bytes) -> str | None:
    """
    Resolve the identifier owned by one declarator node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declarator node that may nest pointers, references, or arrays.
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

    if node.type in {
        "identifier",
        "field_identifier",
        "type_identifier",
        "namespace_identifier",
        "qualified_identifier",
        "destructor_name",
        "operator_name",
    }:
        return _canonical_node_text(node, source)

    child = node.child_by_field_name("declarator")
    if child is not None:
        return _unwrap_declarator_name(child, source)

    for named_child in node.named_children:
        name = _unwrap_declarator_name(named_child, source)
        if name is not None:
            return name
    return None


def _extract_parameter_names(
    parameter_list: Node | None,
    source: bytes,
) -> tuple[str, ...]:
    """
    Extract deterministic parameter names from one parameter list.

    Parameters
    ----------
    parameter_list : tree_sitter.Node | None
        Parameter list node from a function declarator.
    source : bytes
        Full source buffer.

    Returns
    -------
    tuple[str, ...]
        Parameter names in declaration order.
    """
    if parameter_list is None:
        return ()

    parameters: list[str] = []
    for child in parameter_list.named_children:
        if child.type not in {
            "parameter_declaration",
            "optional_parameter_declaration",
            "variadic_parameter_declaration",
        }:
            continue
        declarator = child.child_by_field_name("declarator")
        if declarator is None:
            continue
        name = _parameter_name_node(declarator)
        if name is not None:
            parameters.append(_node_text(name, source))
    return tuple(parameters)


def _parameter_name_node(declarator: Node) -> Node | None:
    """Follow the declarator chain to an explicitly named parameter.

    Parameters
    ----------
    declarator : tree_sitter.Node
        Parameter declarator, possibly a pointer, array or callback signature.

    Returns
    -------
    tree_sitter.Node | None
        Declared parameter identifier, excluding type and nested parameter names.
    """
    current: Node | None = declarator
    while current is not None:
        if current.type in {"identifier", "field_identifier"}:
            return current
        nested = current.child_by_field_name("declarator")
        if nested is None and current.type in {
            "parenthesized_declarator",
            "reference_declarator",
            "variadic_declarator",
        }:
            nested = next(
                (
                    child
                    for child in current.named_children
                    if child.type.endswith("_declarator")
                    or child.type in {"identifier", "field_identifier"}
                ),
                None,
            )
        current = nested
    return None


def _callable_binding_key(declarator: Node, source: bytes) -> tuple[str, ...]:
    """Distinguish written overload types while merging named redeclarations.

    Parameters
    ----------
    declarator : tree_sitter.Node
        Function declarator selected by declared-name binding.
    source : bytes
        Original source used to retain explicit annotation/type spelling.

    Returns
    -------
    tuple[str, ...]
        Parameter, cv/ref/constraint and lexical conditional-branch syntax. This
        does not resolve type aliases or compiler-dependent type equivalence.
    """
    parameters = declarator.child_by_field_name("parameters")
    if parameters is None:
        return ()
    types: list[str] = []
    for parameter in parameters.named_children:
        if parameter.type == "comment":
            continue
        excluded: set[tuple[int, int]] = set()
        pending = [parameter]
        while pending:
            child = pending.pop()
            if child.type == "parameter_list":
                written = [
                    item for item in child.named_children if item.type != "comment"
                ]
                if (
                    len(written) == 1
                    and written[0].type == "parameter_declaration"
                    and _canonical_node_text(written[0], source) == "void"
                ):
                    excluded.add((written[0].start_byte, written[0].end_byte))
            if child.type in {
                "parameter_declaration",
                "optional_parameter_declaration",
                "variadic_parameter_declaration",
            }:
                named = child.child_by_field_name("declarator")
                name = _parameter_name_node(named) if named is not None else None
                if name is not None:
                    excluded.add((name.start_byte, name.end_byte))
                default = child.child_by_field_name("default_value")
                if default is not None:
                    excluded.add((default.start_byte, default.end_byte))
                    excluded.update(
                        (item.start_byte, item.end_byte)
                        for item in child.children
                        if item.type == "="
                    )
            pending.extend(child.named_children)
        types.append(
            _canonical_node_text(parameter, source, excluded=frozenset(excluded))
        )
    if types == ["void"]:
        types.clear()
    if any(child.type == "..." for child in parameters.children):
        types.append("...")
    qualifiers = " ".join(
        _canonical_node_text(child, source)
        for child in declarator.named_children
        if child.type in {"type_qualifier", "ref_qualifier", "requires_clause"}
    )
    conditions: list[str] = []
    parent = declarator.parent
    while parent is not None:
        if parent.type in {
            "preproc_if",
            "preproc_ifdef",
            "preproc_else",
            "preproc_elif",
        }:
            conditions.append(f"{parent.type}:{parent.start_byte}")
        parent = parent.parent
    return (*types, qualifiers, "/".join(conditions))


def _qualified_call_parts(node: Node, source: bytes) -> tuple[str, ...]:
    """Read qualified call components without splitting template arguments.

    Parameters
    ----------
    node : tree_sitter.Node
        Qualified function expression, including nested scope components.
    source : bytes
        Original source buffer used for target and template argument spelling.

    Returns
    -------
    tuple[str, ...]
        Ordered scope components and final target, preserving argument text.
    """
    parts: list[str] = []
    current = node
    while current.type == "qualified_identifier":
        scope = current.child_by_field_name("scope")
        if scope is not None:
            parts.append(_node_text(scope, source).strip())
        name = current.child_by_field_name("name")
        if name is None:
            return ()
        current = name
    parts.append(_node_text(current, source).strip())
    return tuple(part for part in parts if part)


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
        Normalized call record, excluding primitive conversions, named casts,
        noexcept expressions and unsupported operators.
        Calls inside their operands are collected separately by body traversal.
    """
    if _is_complex_operator_call(node, source):
        return None
    function_node = node.child_by_field_name("function")
    if function_node is None:
        return None
    function_text = (
        _decode_source_text(function_node.syntax_text)
        if isinstance(function_node, _ProjectedNode)
        else _node_text(function_node, source)
    )
    if function_node.type == "identifier" and function_text == "noexcept":
        return None
    if function_node.type == "primitive_type" or (
        function_node.type == "identifier"
        and function_text in {"short", "long", "signed", "unsigned", "wchar_t"}
    ):
        return None

    if function_node.type == "template_function":
        name = function_node.child_by_field_name("name")
        name_text = (
            _decode_source_text(name.syntax_text)
            if isinstance(name, _ProjectedNode)
            else _node_text(name, source)
            if name is not None
            else ""
        )
        if name is not None and name_text in {
            "static_cast",
            "reinterpret_cast",
            "const_cast",
            "dynamic_cast",
        }:
            return None

    if function_node.type in {"identifier", "template_function"}:
        target = _node_text(function_node, source)
        return CallSite(
            kind="name",
            target=target,
            lineno=function_node.start_point.row + 1,
            col_offset=function_node.start_point.column,
            external_target_kind=_cpp_external_target_kind("", target),
            external_target_name=target,
        )

    if function_node.type == "qualified_identifier":
        target_parts = _qualified_call_parts(function_node, source)
        if not target_parts:
            return None
        base = "::".join(target_parts[:-1])
        return CallSite(
            kind="name",
            target=target_parts[-1],
            lineno=function_node.start_point.row + 1,
            col_offset=function_node.start_point.column,
            base=base,
            external_target_kind=_cpp_external_target_kind(base, target_parts[-1]),
            external_target_name="::".join(target_parts),
        )

    if function_node.type == "field_expression":
        receiver = function_node.child_by_field_name("argument")
        field = function_node.child_by_field_name("field")
        if receiver is None or field is None:
            return None
        target = _node_text(field, source)
        base = _node_text(receiver, source)
        return CallSite(
            kind="attribute",
            target=target,
            lineno=field.start_point.row + 1,
            col_offset=field.start_point.column,
            base=base,
            external_target_kind=_cpp_external_target_kind(base, target),
            external_target_name=f"{base}.{target}",
        )

    return CallSite(
        kind="unresolved",
        target="",
        lineno=function_node.start_point.row + 1,
        col_offset=function_node.start_point.column,
    )


def _initializer_argument_calls(
    body: Node, source: bytes, parameter_names: tuple[str, ...]
) -> tuple[CallSite, ...]:
    """Recover expression arguments when a value parameter excludes a prototype.

    Parameters
    ----------
    body : Node
        Function compound statement; nested scopes are not adapted.
    source : bytes
        Coordinate-aligned original source.
    parameter_names : tuple[str, ...]
        Explicit value parameters belonging to this function.

    Returns
    -------
    tuple[CallSite, ...]
        Nested argument calls at original byte positions. The declared variable
        and synthetic expression wrapper never acquire call records.
    """
    if not parameter_names:
        return ()
    recovered: list[CallSite] = []
    original_lines: list[int] | None = None
    prefix = b"void __codira_probe() { __codira_probe"
    for declaration in body.named_children:
        if declaration.type != "declaration":
            continue
        declarator = declaration.child_by_field_name("declarator")
        if declarator is None or declarator.type != "function_declarator":
            continue
        parameters = declarator.child_by_field_name("parameters")
        if parameters is None:
            continue
        arguments = [n for n in parameters.named_children if n.type != "comment"]
        if len(arguments) < 2 or arguments[0].type != "parameter_declaration":
            continue
        first = arguments[0]
        written = [n for n in first.named_children if n.type != "comment"]
        value = first.child_by_field_name("type")
        if (
            len(written) != 1
            or value is None
            or value.type != "type_identifier"
            or _node_text(value, source) not in parameter_names
        ):
            continue
        # A parameter cannot be redeclared as a type in this outermost block.
        # Reparse only the proven initializer arguments, excluding its variable.
        fragment = prefix + source[parameters.start_byte : parameters.end_byte]
        fragment += b"; }"
        root = _new_parser().parse(fragment).root_node
        if root.has_error:
            continue
        fragment_lines = [0, *(i + 1 for i, byte in enumerate(fragment) if byte == 10)]
        for node in _named_descendants(root):
            if node.type != "call_expression" or node.start_byte < len(prefix):
                continue
            call = _call_site_from_expression(node, fragment)
            if call is None:
                continue
            offset = (
                parameters.start_byte
                + fragment_lines[call.lineno - 1]
                + call.col_offset
                - len(prefix)
            )
            if not parameters.start_byte <= offset < parameters.end_byte:
                continue
            if original_lines is None:
                original_lines = [
                    0,
                    *(i + 1 for i, byte in enumerate(source) if byte == 10),
                ]
            line = bisect_right(original_lines, offset)
            recovered.append(
                replace(call, lineno=line, col_offset=offset - original_lines[line - 1])
            )
    return tuple(recovered)


def _extract_calls(
    body: Node | None,
    source: bytes,
    *,
    parameter_names: tuple[str, ...] = (),
) -> tuple[CallSite, ...]:
    """
    Extract normalized calls from one function body.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Compound-statement node owning the function body.
    source : bytes
        Full source buffer.
    parameter_names : tuple[str, ...], optional
        Explicit value parameters licensing direct initializer disambiguation.

    Returns
    -------
    tuple[codira.models.CallSite, ...]
        Call records in deterministic source order, including written operands
        erased by a source-selected statement macro.
    """
    if body is None:
        return ()

    calls: list[CallSite] = []
    statement_hints = False
    for node in _named_descendants(body):
        if isinstance(node, _ProjectedNode) and node.macro_hint is not None:
            statement_hints = True
            calls.append(
                CallSite(
                    kind="name",
                    target=node.macro_hint,
                    lineno=node.start_point.row + 1,
                    col_offset=node.start_point.column,
                    external_target_kind="C++:<macro>",
                    external_target_name=node.macro_hint,
                )
            )
            if node.macro_arguments is not None:
                calls.extend(
                    _extract_calls(
                        node.macro_arguments,
                        source,
                        parameter_names=parameter_names,
                    )
                )
        if node.type != "call_expression":
            continue
        call = _call_site_from_expression(node, source)
        if call is not None:
            calls.append(call)
    if statement_hints:
        calls = list(dict.fromkeys(calls))
    seen = set(calls)
    recovered: list[CallSite] = []
    for call in _initializer_argument_calls(body, source, parameter_names):
        if call not in seen:
            seen.add(call)
            recovered.append(call)
    if not recovered:
        return tuple(calls)
    recovered.sort(key=lambda call: (call.lineno, call.col_offset))
    merged: list[CallSite] = []
    pending = iter(recovered)
    next_call = next(pending, None)
    for call in calls:
        while next_call is not None and (next_call.lineno, next_call.col_offset) < (
            call.lineno,
            call.col_offset,
        ):
            merged.append(next_call)
            next_call = next(pending, None)
        merged.append(call)
    if next_call is not None:
        merged.append(next_call)
    merged.extend(pending)
    return tuple(merged)


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
        ``1`` when the body contains `return <expr>;`, else ``0``.
    """
    if body is None:
        return 0
    for node in _named_descendants(body):
        if node.type == "return_statement" and len(node.named_children) > 0:
            return 1
    return 0


def _find_function_declarator(node: Node) -> Node | None:
    """
    Follow the declared name's binding to distinguish functions from pointers.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration-like node to inspect.

    Returns
    -------
    tree_sitter.Node | None
        Callable declarator when the name binds as a function. Function-pointer
        variables and parameter or initializer subtrees are not callable owners.
    """
    current = (
        node
        if node.type == "function_declarator"
        else node.child_by_field_name("declarator")
    )
    function: Node | None = None
    binds_as_function = False
    while current is not None:
        if current.type == "function_declarator":
            if function is None:
                function = current
            binds_as_function = True
        elif current.type in {
            "pointer_declarator",
            "reference_declarator",
            "array_declarator",
        }:
            function = None
            binds_as_function = False
        nested = current.child_by_field_name("declarator")
        if nested is None and current.type in {
            "parenthesized_declarator",
            "reference_declarator",
        }:
            nested = next(
                (
                    child
                    for child in current.named_children
                    if child.type.endswith("_declarator")
                    or child.type
                    in {"identifier", "field_identifier", "qualified_identifier"}
                ),
                None,
            )
        current = nested
    return function if binds_as_function else None


def _declared_type_specifier(node: Node) -> Node | None:
    """Find an explicitly declared record or enum without entering nested scopes.

    Parameters
    ----------
    node : tree_sitter.Node
        Type specifier or declaration that may also declare a variable.

    Returns
    -------
    tree_sitter.Node | None
        Direct record/enum specifier, excluding types hidden in initializers.
    """
    types = {"class_specifier", "struct_specifier", "union_specifier", "enum_specifier"}
    if node.type in types:
        return node
    if node.type in {"declaration", "field_declaration", "type_definition"}:
        declared_type = node.child_by_field_name("type")
        if declared_type is not None and declared_type.type in types:
            return declared_type
    return None


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
                signature=_normalize_signature(_node_text(enumerator, source)),
                lineno=enumerator.start_point.row + 1,
            )
        )
    return tuple(members)


def _prefer_pending_function(
    current: _PendingFunction,
    candidate: _PendingFunction,
) -> _PendingFunction:
    """
    Choose the richer callable candidate for one logical signature slot.

    Parameters
    ----------
    current : _PendingFunction
        Previously recorded callable candidate.
    candidate : _PendingFunction
        New callable candidate competing for the same slot.

    Returns
    -------
    _PendingFunction
        Preferred callable candidate.
    """
    if current.is_definition != candidate.is_definition:
        preferred = candidate if candidate.is_definition else current
        alternate = current if candidate.is_definition else candidate
    elif (
        current.artifact.docstring is None and candidate.artifact.docstring is not None
    ):
        preferred = candidate
        alternate = current
    elif (
        current.artifact.end_lineno is None
        and candidate.artifact.end_lineno is not None
    ):
        preferred = candidate
        alternate = current
    elif len(current.artifact.calls) < len(candidate.artifact.calls):
        preferred = candidate
        alternate = current
    else:
        preferred = current
        alternate = candidate

    if (
        preferred.artifact.docstring is None
        and alternate.artifact.docstring is not None
    ):
        preferred = replace(
            preferred,
            artifact=replace(
                preferred.artifact,
                docstring=alternate.artifact.docstring,
                has_docstring=alternate.artifact.has_docstring,
            ),
        )
    return preferred


def _disambiguate_callable_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Disambiguate duplicate callable stable IDs within one file analysis.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Extracted callable artifacts in deterministic order.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Callable artifacts with duplicate stable IDs rewritten deterministically.
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


def _is_likely_public_definition(node: Node, source: bytes) -> int:
    """
    Infer whether one free function definition should be treated as public.

    Parameters
    ----------
    node : tree_sitter.Node
        Function-definition node.
    source : bytes
        Full source buffer.

    Returns
    -------
    int
        ``1`` when the definition does not carry `static`, else ``0``.
    """
    return int(
        not any(
            child.type == "storage_class_specifier"
            and _node_text(child, source) == "static"
            for child in node.children
        )
    )


def _build_namespace_declaration(
    namespace_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one namespace declaration artifact.

    Parameters
    ----------
    namespace_name : str
        Qualified namespace name.
    node : tree_sitter.Node
        Namespace-definition node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the namespace declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized namespace declaration artifact.
    """
    return DeclarationArtifact(
        name=namespace_name,
        stable_id=_declaration_stable_id(owner_id, "namespace", namespace_name),
        kind="namespace",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _build_alias_declaration(
    alias_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one alias-declaration artifact.

    Parameters
    ----------
    alias_name : str
        Qualified alias name.
    node : tree_sitter.Node
        Alias-declaration node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the alias declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized alias declaration artifact.
    """
    return DeclarationArtifact(
        name=alias_name,
        stable_id=_declaration_stable_id(owner_id, "type_alias", alias_name),
        kind="type_alias",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _macro_name(node: Node, source: bytes) -> str | None:
    """
    Extract the declared macro name from one preprocessor definition.

    Parameters
    ----------
    node : tree_sitter.Node
        Preprocessor definition node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Macro identifier when present.
    """
    identifier = next(
        (child for child in node.named_children if child.type == "identifier"),
        None,
    )
    if identifier is None:
        return None
    return _node_text(identifier, source)


def _build_macro_declaration(
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact | None:
    """
    Build one preprocessor macro declaration artifact when named.

    Parameters
    ----------
    node : tree_sitter.Node
        Preprocessor definition node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the macro declaration.

    Returns
    -------
    codira.models.DeclarationArtifact | None
        Normalized macro declaration artifact, or ``None`` when no macro name is
        present.
    """
    name = _macro_name(node, source)
    if name is None:
        return None
    return DeclarationArtifact(
        name=name,
        stable_id=_declaration_stable_id(owner_id, "macro", name),
        kind="macro",
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
    )


def _build_type_declaration(
    kind: DeclarationKind,
    qualified_name: str,
    node: Node,
    source: bytes,
    *,
    owner_id: str,
    docstring: str | None,
) -> DeclarationArtifact:
    """
    Build one enum, struct, or union declaration artifact.

    Parameters
    ----------
    kind : codira.models.DeclarationKind
        Stable declaration classifier.
    qualified_name : str
        Qualified declaration name.
    node : tree_sitter.Node
        Type-specifier node.
    source : bytes
        Full source buffer.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Docstring to attach to the declaration.

    Returns
    -------
    codira.models.DeclarationArtifact
        Normalized declaration artifact.
    """
    stable_id = _declaration_stable_id(owner_id, kind, qualified_name)
    return DeclarationArtifact(
        name=qualified_name,
        stable_id=stable_id,
        kind=kind,
        lineno=node.start_point.row + 1,
        signature=_normalize_signature(_node_text(node, source)),
        docstring=docstring,
        enum_members=(
            _extract_enum_members(
                node,
                source,
                owner_id=owner_id,
                enum_name=qualified_name,
                parent_stable_id=stable_id,
            )
            if kind == "enum"
            else ()
        ),
    )


def _class_name_from_specifier(node: Node, source: bytes) -> str | None:
    """
    Extract the declared class name from one class specifier.

    Parameters
    ----------
    node : tree_sitter.Node
        Class-specifier node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Declared class name, including explicit template specialization arguments.
    """
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _canonical_node_text(name_node, source)


def _type_specifier_name(node: Node, source: bytes) -> str | None:
    """
    Extract the declared enum, struct, or union name from one specifier.

    Parameters
    ----------
    node : tree_sitter.Node
        Type-specifier node.
    source : bytes
        Full source buffer.

    Returns
    -------
    str | None
        Declared type name, including explicit template specialization arguments.
    """
    name = node.child_by_field_name("name")
    if name is None:
        return None
    return _canonical_node_text(name, source)


def _is_function_definition(node: Node) -> bool:
    """
    Decide whether one parsed node is a usable function definition.

    Parameters
    ----------
    node : tree_sitter.Node
        Candidate node.

    Returns
    -------
    bool
        ``True`` when the node exposes a callable declarator with parameters.
    """
    if node.type != "function_definition":
        return False
    declarator = node.child_by_field_name("declarator")
    return _find_parameter_list(declarator) is not None


def _resolve_callable_identity(
    raw_name: str,
    *,
    namespace: Sequence[str],
    known_class_names: set[str],
) -> tuple[str, str | None]:
    """
    Resolve the qualified callable name and optional owning class.

    Parameters
    ----------
    raw_name : str
        Declarator-owned callable text.
    namespace : collections.abc.Sequence[str]
        Active namespace context.
    known_class_names : set[str]
        Qualified class names collected from the file.

    Returns
    -------
    tuple[str, str | None]
        Resolved callable name plus owning class when identified.
    """
    parts = _split_qualified_name(raw_name)
    if not parts:
        return raw_name, None
    if len(parts) == 1:
        if namespace:
            return _qualified_name((*namespace, parts[0])), None
        return parts[0], None

    relative_owner = _qualified_name((*namespace, *parts[:-1]))
    if relative_owner in known_class_names:
        return parts[-1], relative_owner
    if any(relative_owner.startswith(name + "<") for name in known_class_names):
        return parts[-1], relative_owner

    qualified_name = _qualified_name((*namespace, *parts))
    return qualified_name, None


def _build_function_artifact(
    node: Node,
    source: bytes,
    *,
    namespace: Sequence[str],
    known_class_names: set[str],
    owner_id: str,
    docstring: str | None,
    is_public: int,
    signature_node: Node,
) -> _PendingFunction | None:
    """
    Build one function or method artifact from a definition or declaration node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration-like node that owns the callable.
    source : bytes
        Full source buffer.
    namespace : collections.abc.Sequence[str]
        Active namespace context.
    known_class_names : set[str]
        Qualified class names collected from the file.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    docstring : str | None
        Attached comment summary when present.
    is_public : int
        Public-visibility flag for the callable.
    signature_node : tree_sitter.Node
        Node whose source span should be used for signature extraction.

    Returns
    -------
    _PendingFunction | None
        Callable candidate when the node exposes a supported declarator.
    """
    declarator = _find_function_declarator(node)
    if declarator is None:
        return None

    raw_name = _unwrap_declarator_name(declarator, source)
    if raw_name is None:
        return None

    resolved_name, class_name = _resolve_callable_identity(
        raw_name,
        namespace=namespace,
        known_class_names=known_class_names,
    )
    method_name = resolved_name.split("::")[-1]
    parameter_list = _find_parameter_list(declarator)
    parameters = _extract_parameter_names(parameter_list, source)
    body = node.child_by_field_name("body")
    children: Sequence[Node] = node.named_children
    bodyless_definition = node.type == "function_definition" and any(
        child.type in {"default_method_clause", "delete_method_clause"}
        for child in children
    )
    if node.type in {"declaration", "field_declaration"}:
        suffix = source[declarator.end_byte : node.end_byte]
        suffix = re.sub(rb"/\*[\s\S]*?\*/|//[^\r\n]*", b" ", suffix)
        bodyless_definition = re.fullmatch(rb"\s*=\s*delete\s*;", suffix) is not None
    definition_end = (
        body.end_point.row + 1
        if body is not None
        else node.end_point.row + 1
        if bodyless_definition
        else None
    )
    signature_end = body.start_byte if body is not None else signature_node.end_byte
    signature_start = _original_declaration_start(signature_node, source)
    signature = _decode_source_text(source[signature_start:signature_end]).strip()

    artifact = FunctionArtifact(
        name=method_name if class_name is not None else resolved_name,
        stable_id=_function_stable_id(
            owner_id,
            method_name if class_name is not None else resolved_name,
            class_name=class_name,
        ),
        lineno=(
            signature_node.start_point.row
            + 1
            - source.count(b"\n", signature_start, signature_node.start_byte)
        ),
        end_lineno=definition_end,
        signature=_normalize_signature(signature),
        docstring=docstring,
        has_docstring=int(docstring is not None),
        is_method=int(class_name is not None),
        is_public=is_public,
        parameters=parameters,
        returns_value=_returns_value(body),
        yields_value=0,
        raises=0,
        has_asserts=0,
        decorators=(),
        calls=_extract_calls(body, source, parameter_names=parameters),
        callable_refs=(),
    )
    return _PendingFunction(
        artifact=artifact,
        class_name=class_name,
        is_definition=definition_end is not None,
        binding_key=_callable_binding_key(declarator, source),
    )


def _collect_known_class_names(
    children: Sequence[Node],
    source: bytes,
    *,
    namespace: Sequence[str] = (),
) -> set[str]:
    """
    Collect qualified class names declared within one subtree.

    Parameters
    ----------
    children : collections.abc.Sequence[tree_sitter.Node]
        Sibling nodes to inspect.
    source : bytes
        Full source buffer.
    namespace : collections.abc.Sequence[str], optional
        Active namespace prefix for the current subtree.

    Returns
    -------
    set[str]
        Qualified class names declared in the subtree.
    """
    known: set[str] = set()
    for child in _conditional_children(children):
        if child.type == "linkage_specification":
            body = child.child_by_field_name("body")
            if body is not None:
                known.update(
                    _collect_known_class_names(
                        body.named_children
                        if body.type == "declaration_list"
                        else (body,),
                        source,
                        namespace=namespace,
                    )
                )
            continue
        if child.type == "template_declaration":
            inner = _template_inner_node(child)
            if inner is not None:
                known.update(
                    _collect_known_class_names((inner,), source, namespace=namespace)
                )
            continue

        if child.type == "namespace_definition":
            declaration_list = next(
                (
                    grandchild
                    for grandchild in child.named_children
                    if grandchild.type == "declaration_list"
                ),
                None,
            )
            if declaration_list is None:
                continue
            namespace_parts = _namespace_parts(child, source)
            known.update(
                _collect_known_class_names(
                    declaration_list.named_children,
                    source,
                    namespace=(*namespace, *namespace_parts),
                )
            )
            continue

        record = _declared_type_specifier(child)
        if record is None or record.type == "enum_specifier":
            continue
        class_name = _class_name_from_specifier(record, source)
        if class_name is None:
            continue
        known.add(_qualified_name((*namespace, class_name)))
        body = record.child_by_field_name("body")
        if body is not None:
            known.update(
                _collect_known_class_names(
                    body.named_children, source, namespace=(*namespace, class_name)
                )
            )
    return known


class _CppAnalysisBuilder:
    """
    Mutable builder for one C++ analysis result.

    Parameters
    ----------
    source : bytes
        Full source buffer for the analyzed file.
    root : tree_sitter.Node
        Translation-unit root node.
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    known_class_names : set[str]
        Qualified class names collected from the file.
    comment_maps : CommentMaps or None, optional
        Unmasked source attachment facts, independent of syntax visibility.

    Returns
    -------
    None
    """

    def __init__(
        self,
        *,
        source: bytes,
        root: Node,
        owner_id: str,
        known_class_names: set[str],
        comment_maps: CommentMaps | None = None,
    ) -> None:
        """Initialize artifact accumulators and optional physical comment facts.

        Parameters
        ----------
        source : bytes
            Buffer used for declaration and callable extraction.
        root : SyntaxNode
            Syntax view rooted in the same coordinate space.
        owner_id : str
            File-scoped symbol identity.
        known_class_names : set[str]
            Collected qualified class names.
        comment_maps : CommentMaps or None, optional
            Attachments captured before visibility projection.

        Returns
        -------
        None
        """
        self.source = source
        self.root = root
        self.owner_id = owner_id
        self.known_class_names = known_class_names
        self.class_builders: dict[str, _ClassBuilder] = {}
        self.functions_by_key: dict[tuple[str, tuple[str, ...]], _PendingFunction] = {}
        self.declarations_by_id: dict[str, DeclarationArtifact] = {}
        self.doxygen_by_lineno: dict[int, tuple[str, int, int | None]] = {}
        self.source_comments = comment_maps[0] if comment_maps is not None else None
        if comment_maps is not None:
            self.doxygen_by_lineno.update(comment_maps[1])

    def _ensure_class_builder(
        self,
        *,
        qualified_name: str,
        lineno: int,
        end_lineno: int | None,
        docstring: str | None,
    ) -> _ClassBuilder:
        """
        Return the mutable builder for one class, creating it when needed.

        Parameters
        ----------
        qualified_name : str
            Qualified class name.
        lineno : int
            Candidate starting line for the class.
        end_lineno : int | None
            Candidate ending line for the class.
        docstring : str | None
            Candidate docstring attached to the class.

        Returns
        -------
        _ClassBuilder
            Mutable class accumulator.
        """
        stable_id = _class_stable_id(self.owner_id, qualified_name)
        builder = self.class_builders.get(qualified_name)
        if builder is None:
            builder = _ClassBuilder(
                qualified_name=qualified_name,
                stable_id=stable_id,
                lineno=lineno,
                end_lineno=end_lineno,
                docstring=docstring,
                has_docstring=int(docstring is not None),
            )
            self.class_builders[qualified_name] = builder
            return builder
        builder.absorb_metadata(
            lineno=lineno,
            end_lineno=end_lineno,
            docstring=docstring,
        )
        return builder

    def _record_function(self, pending: _PendingFunction) -> None:
        """
        Record one function or method candidate.

        Parameters
        ----------
        pending : _PendingFunction
            Callable candidate to store.

        Returns
        -------
        None
            The appropriate function accumulator is updated in place.
        """
        if pending.class_name is None:
            key = (pending.artifact.stable_id, pending.binding_key)
            current = self.functions_by_key.get(key)
            if current is None or _prefer_pending_function(current, pending) is pending:
                self.functions_by_key[key] = pending
            return

        builder = self._ensure_class_builder(
            qualified_name=pending.class_name,
            lineno=pending.artifact.lineno,
            end_lineno=None,
            docstring=None,
        )
        builder.record_method(pending)

    def _record_declaration(self, declaration: DeclarationArtifact | None) -> None:
        """
        Record one declaration artifact when present.

        Parameters
        ----------
        declaration : codira.models.DeclarationArtifact | None
            Declaration artifact to store.

        Returns
        -------
        None
            The declaration map is updated in place when a declaration exists.
        """
        if declaration is not None:
            self.declarations_by_id[declaration.stable_id] = declaration

    def _handle_type_declaration(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record one enum, struct, or union declaration.

        Parameters
        ----------
        node : tree_sitter.Node
            Type-specifier node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Matching declaration artifacts are stored in place.
        """
        if node.type == "enum_specifier":
            kind: DeclarationKind = "enum"
        elif node.type == "struct_specifier":
            kind = "struct"
        elif node.type == "union_specifier":
            kind = "union"
        else:
            return

        name = _type_specifier_name(node, self.source)
        if name is None:
            return
        qualified_name = _qualified_name((*namespace, name))
        self._record_declaration(
            _build_type_declaration(
                kind,
                qualified_name,
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )

    def _handle_typedef_definition(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """Record every written alias in one module or class typedef.

        Parameters
        ----------
        node : SyntaxNode
            Complete typedef declaration, including its original signature.
        namespace : collections.abc.Sequence[str]
            Enclosing namespace and class path.
        docstring : str | None
            Leading declaration documentation when present.

        Returns
        -------
        None
            Qualified typedef artifacts are stored without visiting local scopes.
        """
        for name in _typedef_name_nodes(node):
            self._record_declaration(
                _build_type_declaration(
                    "typedef",
                    _qualified_name((*namespace, _node_text(name, self.source))),
                    node,
                    self.source,
                    owner_id=self.owner_id,
                    docstring=docstring,
                )
            )

    def _handle_alias_declaration(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record one `using` alias declaration.

        Parameters
        ----------
        node : tree_sitter.Node
            Alias-declaration node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Matching declaration artifacts are stored in place.
        """
        alias_name = next(
            (
                _node_text(child, self.source)
                for child in node.named_children
                if child.type in {"type_identifier", "identifier"}
            ),
            None,
        )
        if alias_name is None:
            return
        self._record_declaration(
            _build_alias_declaration(
                _qualified_name((*namespace, alias_name)),
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )

    def _handle_macro_declaration(
        self,
        node: Node,
        *,
        docstring: str | None,
    ) -> None:
        """
        Record one named preprocessor macro declaration.

        Parameters
        ----------
        node : tree_sitter.Node
            Preprocessor definition node.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Matching macro declaration artifacts are stored in place.
        """
        self._record_declaration(
            _build_macro_declaration(
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )

    def _handle_namespace(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record one namespace declaration and recurse into its body.

        Parameters
        ----------
        node : tree_sitter.Node
            Namespace-definition node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Namespace artifacts and nested declarations are stored in place.
        """
        namespace_parts = _namespace_parts(node, self.source)
        if not namespace_parts:
            return
        full_namespace = (*namespace, *namespace_parts)
        self._record_declaration(
            _build_namespace_declaration(
                _qualified_name(full_namespace),
                node,
                self.source,
                owner_id=self.owner_id,
                docstring=docstring,
            )
        )
        declaration_list = next(
            (
                child
                for child in node.named_children
                if child.type == "declaration_list"
            ),
            None,
        )
        if declaration_list is None:
            return
        self._visit_children(
            declaration_list.named_children,
            namespace=full_namespace,
        )

    def _handle_class_specifier(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
    ) -> None:
        """
        Record class-like methods, member type aliases and nested record declarations.

        Parameters
        ----------
        node : tree_sitter.Node
            Class, struct or union specifier. Struct/union method containers
            are created only when explicit methods are present.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Class, method and qualified member-alias artifacts are stored in place.
        """
        class_name = _class_name_from_specifier(node, self.source)
        if class_name is None:
            return
        qualified_name = _qualified_name((*namespace, class_name))
        field_list = next(
            (
                child
                for child in node.named_children
                if child.type == "field_declaration_list"
            ),
            None,
        )
        builder = (
            self._ensure_class_builder(
                qualified_name=qualified_name,
                lineno=node.start_point.row + 1,
                end_lineno=node.end_point.row + 1,
                docstring=docstring,
            )
            if node.type == "class_specifier"
            else None
        )
        if field_list is None:
            return

        current_public = node.type in {"struct_specifier", "union_specifier"}
        children = tuple(_conditional_children(field_list.children))
        attached_comments = self.source_comments
        if attached_comments is None:
            attached_comments = _attached_comment_map(children, self.source)
            self.doxygen_by_lineno.update(
                _attached_doxygen_comment_map(children, self.source)
            )
        for child in children:
            if child.type == "access_specifier":
                current_public = _node_text(child, self.source) in {
                    "public",
                    "protected",
                }
                continue

            child_docstring = attached_comments.get(child.start_byte)
            candidate = (
                _template_inner_node(child)
                if child.type == "template_declaration"
                else child
            )
            if candidate is not None and candidate.type == "type_definition":
                self._dispatch_node(
                    candidate,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                    signature_node=child,
                )
                continue
            if candidate is not None and candidate.type == "alias_declaration":
                self._handle_alias_declaration(
                    candidate,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                )
                continue
            nested_type = (
                _declared_type_specifier(candidate) if candidate is not None else None
            )
            if nested_type is not None:
                self._dispatch_node(
                    nested_type,
                    namespace=(*namespace, class_name),
                    docstring=child_docstring,
                    signature_node=child,
                )
                continue
            if child.type == "template_declaration":
                inner = _template_inner_node(child)
                if inner is None:
                    continue
                pending = _build_function_artifact(
                    inner,
                    self.source,
                    namespace=namespace,
                    known_class_names=self.known_class_names,
                    owner_id=self.owner_id,
                    docstring=child_docstring,
                    is_public=int(current_public),
                    signature_node=child,
                )
                if pending is not None:
                    pending = replace(
                        pending,
                        class_name=qualified_name,
                        artifact=replace(
                            pending.artifact,
                            name=pending.artifact.name.split("::")[-1],
                            stable_id=_function_stable_id(
                                self.owner_id,
                                pending.artifact.name.split("::")[-1],
                                class_name=qualified_name,
                            ),
                            is_method=1,
                        ),
                    )
                    if builder is None:
                        builder = self._ensure_class_builder(
                            qualified_name=qualified_name,
                            lineno=node.start_point.row + 1,
                            end_lineno=node.end_point.row + 1,
                            docstring=docstring,
                        )
                    builder.record_method(pending)
                continue

            pending = _build_function_artifact(
                child,
                self.source,
                namespace=namespace,
                known_class_names=self.known_class_names,
                owner_id=self.owner_id,
                docstring=child_docstring,
                is_public=int(current_public),
                signature_node=child,
            )
            if pending is None:
                continue
            pending = replace(
                pending,
                class_name=qualified_name,
                artifact=replace(
                    pending.artifact,
                    name=pending.artifact.name.split("::")[-1],
                    stable_id=_function_stable_id(
                        self.owner_id,
                        pending.artifact.name.split("::")[-1],
                        class_name=qualified_name,
                    ),
                    is_method=1,
                ),
            )
            if builder is None:
                builder = self._ensure_class_builder(
                    qualified_name=qualified_name,
                    lineno=node.start_point.row + 1,
                    end_lineno=node.end_point.row + 1,
                    docstring=docstring,
                )
            builder.record_method(pending)

    def _handle_callable_node(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
        signature_node: Node,
    ) -> None:
        """
        Record one free function or out-of-class method candidate.

        Parameters
        ----------
        node : tree_sitter.Node
            Function-definition or declaration node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.
        signature_node : tree_sitter.Node
            Node whose source span should seed signature extraction.

        Returns
        -------
        None
            Matching callable artifacts are stored in place.
        """
        pending = _build_function_artifact(
            node,
            self.source,
            namespace=namespace,
            known_class_names=self.known_class_names,
            owner_id=self.owner_id,
            docstring=docstring,
            is_public=_is_likely_public_definition(node, self.source),
            signature_node=signature_node,
        )
        if pending is not None:
            self._record_function(pending)

    def _dispatch_node(
        self,
        node: Node,
        *,
        namespace: Sequence[str],
        docstring: str | None,
        signature_node: Node,
    ) -> None:
        """
        Dispatch one node to the matching C++ extraction handler.

        Parameters
        ----------
        node : tree_sitter.Node
            Node to inspect.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.
        signature_node : tree_sitter.Node
            Node whose source span should seed signature extraction when needed.

        Returns
        -------
        None
            Matching artifacts are stored in place.
        """
        if node.type in {"preproc_def", "preproc_function_def"}:
            self._handle_macro_declaration(node, docstring=docstring)
            return
        if node.type == "template_declaration":
            inner = _template_inner_node(node)
            if inner is not None:
                self._dispatch_node(
                    inner,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
            return
        if node.type == "linkage_specification":
            body = node.child_by_field_name("body")
            if body is not None:
                if body.type == "declaration_list":
                    self._visit_children(body.named_children, namespace=namespace)
                else:
                    self._dispatch_node(
                        body,
                        namespace=namespace,
                        docstring=docstring,
                        signature_node=signature_node,
                    )
            return
        if node.type == "namespace_definition":
            self._handle_namespace(node, namespace=namespace, docstring=docstring)
            return
        if node.type == "class_specifier":
            self._handle_class_specifier(node, namespace=namespace, docstring=docstring)
            return
        if node.type == "type_definition":
            self._handle_typedef_definition(
                node, namespace=namespace, docstring=docstring
            )
            declared_type = _declared_type_specifier(node)
            if declared_type is not None:
                self._dispatch_node(
                    declared_type,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
            return
        if node.type in {"declaration", "field_declaration"}:
            declared_type = _declared_type_specifier(node)
            if declared_type is not None:
                self._dispatch_node(
                    declared_type,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=signature_node,
                )
                if _find_function_declarator(node) is None:
                    return
        if node.type == "alias_declaration":
            self._handle_alias_declaration(
                node, namespace=namespace, docstring=docstring
            )
            return
        if node.type in {"enum_specifier", "struct_specifier", "union_specifier"}:
            self._handle_type_declaration(
                node, namespace=namespace, docstring=docstring
            )
            if node.type in {"struct_specifier", "union_specifier"}:
                self._handle_class_specifier(
                    node, namespace=namespace, docstring=docstring
                )
            return
        if _is_function_definition(node):
            self._handle_callable_node(
                node,
                namespace=namespace,
                docstring=docstring,
                signature_node=signature_node,
            )
            return
        if (
            node.type in {"declaration", "field_declaration"}
            and _find_function_declarator(node) is not None
        ):
            self._handle_callable_node(
                node,
                namespace=namespace,
                docstring=docstring,
                signature_node=signature_node,
            )

    def _visit_children(
        self,
        children: Sequence[Node],
        *,
        namespace: Sequence[str],
    ) -> None:
        """
        Visit one sibling list under a shared namespace context.

        Parameters
        ----------
        children : collections.abc.Sequence[tree_sitter.Node]
            Sibling nodes to visit.
        namespace : collections.abc.Sequence[str]
            Active namespace path.

        Returns
        -------
        None
            Matching artifacts are stored in place.
        """
        children = tuple(_conditional_children(children))
        attached_comments = self.source_comments
        if attached_comments is None:
            attached_comments = _attached_comment_map(children, self.source)
            self.doxygen_by_lineno.update(
                _attached_doxygen_comment_map(children, self.source)
            )
        for child in children:
            if child.type in {"comment", "preproc_include"}:
                continue
            docstring = attached_comments.get(child.start_byte)
            if child.type == "template_declaration":
                inner = _template_inner_node(child)
                if inner is None:
                    continue
                self._dispatch_node(
                    inner,
                    namespace=namespace,
                    docstring=docstring,
                    signature_node=child,
                )
                continue
            self._dispatch_node(
                child,
                namespace=namespace,
                docstring=docstring,
                signature_node=child,
            )

    def build(
        self,
        *,
        source_path: Path,
        module_name: str,
        module_stable_id: str,
        module_docstring: str | None,
    ) -> AnalysisResult:
        """
        Finalize the immutable analysis result.

        Parameters
        ----------
        source_path : pathlib.Path
            Source file associated with the analysis.
        module_name : str
            Logical module name for the file.
        module_stable_id : str
            Durable module identity derived from the repository-relative path.
        module_docstring : str | None
            Leading module comment when present.

        Returns
        -------
        codira.models.AnalysisResult
            Final normalized analyzer output.
        """
        imports = _extract_imports(self.root, self.source)
        self._visit_children(self.root.children, namespace=())
        classes = tuple(
            builder.build()
            for builder in sorted(
                self.class_builders.values(),
                key=lambda item: (item.lineno, item.qualified_name),
            )
        )
        functions = tuple(
            pending.artifact
            for pending in sorted(
                self.functions_by_key.values(),
                key=lambda item: (
                    item.artifact.lineno,
                    item.artifact.name,
                    item.artifact.signature,
                ),
            )
        )
        functions = _disambiguate_callable_stable_ids(functions)
        declarations = tuple(
            sorted(
                self.declarations_by_id.values(),
                key=lambda item: (item.lineno, item.name, item.stable_id),
            )
        )
        return AnalysisResult(
            source_path=source_path,
            module=ModuleArtifact(
                name=module_name,
                stable_id=module_stable_id,
                docstring=module_docstring,
                has_docstring=int(module_docstring is not None),
            ),
            classes=classes,
            functions=functions,
            declarations=declarations,
            imports=imports,
        )


_CPP_HEADER_NODES = frozenset(
    {
        "namespace_definition",
        "template_declaration",
        "class_specifier",
        "qualified_identifier",
        "using_declaration",
        "alias_declaration",
        "reference_declarator",
        "rvalue_reference_declarator",
    }
)


def _is_cpp_header(path: Path) -> bool:
    """Recognize C++ headers using neighbouring units and parsed syntax.

    Parameters
    ----------
    path : pathlib.Path
        Ambiguous .h file to inspect; comment and string contents are not hints.

    Returns
    -------
    bool
        True for a C++-only same-stem neighbour, a C++ syntax node or an
        independently parsed named template parameter list. Shared C/C++
        neighbours and syntax without such evidence retain the C default.
    """
    if not path.is_file():
        return False
    cpp_neighbour = any(
        path.with_suffix(suffix).is_file() for suffix in (".cpp", ".cc", ".cxx")
    )
    if cpp_neighbour and not path.with_suffix(".c").is_file():
        return True
    source = path.read_bytes()
    root = _parse_cpp_source(source)
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in _CPP_HEADER_NODES:
            return True
        if node.type not in {"comment", "string_literal", "raw_string_literal"}:
            pending.extend(node.named_children)
    return root.has_error and has_named_template_parameters(source, root)


@dataclass
class _ExternalOwner:
    """Collect source-proven class declarations without emitting their symbols.

    Parameters
    ----------
    stable_ids : set[str]
        Candidate declaration identities from contained headers.
    visibility : dict[str, set[int]]
        Observed access flags for each explicitly declared method name.

    Returns
    -------
    None
        Header evidence for external owner references only.
    """

    stable_ids: set[str] = field(default_factory=set)
    visibility: dict[str, set[int]] = field(default_factory=dict)


def _external_owner_alternatives(result: AnalysisResult) -> set[str]:
    """Retain namespace/alias conflicts without treating member aliases as owners.

    Parameters
    ----------
    result : codira.models.AnalysisResult
        Source-local or captured-header artifacts.

    Returns
    -------
    set[str]
        Existing namespace and nonmember alias alternatives. An alias whose
        direct owner is a written record does not invalidate that record or
        change the legacy treatment of namespace alias prefixes. If a written
        namespace shares the record name in another alternative, its aliases
        retain their conflict evidence.
    """
    namespaces = {
        declaration.name
        for declaration in result.declarations
        if declaration.kind == "namespace"
    }
    records = {cls.name for cls in result.classes} | {
        declaration.name
        for declaration in result.declarations
        if declaration.kind in {"class", "struct", "union"}
    }
    return {
        declaration.name
        for declaration in result.declarations
        if declaration.kind == "namespace"
        or (
            declaration.kind == "type_alias"
            and (
                declaration.name.rpartition("::")[0] not in records
                or declaration.name.rpartition("::")[0] in namespaces
            )
        )
    }


def _external_method_owners(
    context: IncludeContext, root: Path, source_result: AnalysisResult
) -> dict[str, _ExternalOwner]:
    """Find unambiguous class-owner evidence in clean captured header trees.

    Parameters
    ----------
    context : IncludeContext
        Exact source and header snapshot already used for syntax recovery.
    root : pathlib.Path
        Repository boundary used to derive declaration identities.
    source_result : AnalysisResult
        Source-local artifacts whose namespace and alias evidence takes priority.

    Returns
    -------
    dict[str, _ExternalOwner]
        Qualified class names and declaration/access evidence. Header artifacts
        are not copied into the source result. Member aliases are excluded from
        conflicting alternatives so their parent records remain valid owners.
    """
    owners: dict[str, _ExternalOwner] = {}
    alternatives = _external_owner_alternatives(source_result)
    for header in context.headers:
        tree = _parse_cpp_source(header.source)
        if tree.has_error:
            continue
        header_result = _CppAnalysisBuilder(
            source=header.source,
            root=tree,
            owner_id=_symbol_owner_id(header.path, root),
            known_class_names=_collect_known_class_names(tree.children, header.source),
        ).build(
            source_path=header.path,
            module_name=_module_name_for_path(header.path, root),
            module_stable_id=_module_stable_id(header.path, root),
            module_docstring=None,
        )
        alternatives.update(_external_owner_alternatives(header_result))
        for cls in header_result.classes:
            owner = owners.setdefault(cls.name, _ExternalOwner())
            owner.stable_ids.add(cls.stable_id)
            for method in cls.methods:
                owner.visibility.setdefault(method.name, set()).add(method.is_public)
    conflicting_names = {
        _qualified_name(_split_qualified_name(name)[:end])
        for name in alternatives
        for end in range(1, len(_split_qualified_name(name)) + 1)
    }
    return {
        name: owner for name, owner in owners.items() if name not in conflicting_names
    }


def _external_member_calls(
    function: FunctionArtifact,
    owner_name: str,
    owner: _ExternalOwner,
    source: bytes,
    source_tree: Node,
) -> tuple[CallSite, ...]:
    """Qualify proven member calls while retaining ambiguous lexical bindings.

    Parameters
    ----------
    function : FunctionArtifact
        Source-owned method definition and original call sites.
    owner_name : str
        Header-declared qualified class name.
    owner : _ExternalOwner
        Captured method declarations for that class.
    source : bytes
        Original source bytes for lexical names.
    source_tree : tree_sitter.Node
        Recovered source tree with original byte and line positions.

    Returns
    -------
    tuple[CallSite, ...]
        Explicit class-member records where unqualified lookup is proven.
        Local declarations, parameters and nested scopes prevent inference.
    """
    bodies = [
        node.child_by_field_name("body")
        for node in _named_descendants(source_tree)
        if node.type == "function_definition"
        and node.end_point.row + 1 == function.end_lineno
        and node.start_point.row + 1 >= function.lineno
    ]
    if len(bodies) != 1 or bodies[0] is None or len(owner.stable_ids) != 1:
        return function.calls
    nodes = _named_descendants(bodies[0])
    nested_scopes = [
        node
        for node in nodes
        if node.type in {"lambda_expression", "class_specifier", "struct_specifier"}
    ]
    if any(
        node.type == "call_expression"
        and (callee := node.child_by_field_name("function")) is not None
        and callee.type == "primitive_type"
        for node in nodes
    ):
        # The grammar can parse a local function-pointer declaration as nested
        # primitive-type calls. Its lexical bindings are then not proven.
        return function.calls
    shadowed = set(function.parameters)
    for node in nodes:
        if node.type in {"using_declaration", "type_definition"}:
            shadowed.update(
                _node_text(child, source)
                for child in _named_descendants(node)
                if child.type in {"identifier", "type_identifier"}
            )
        for index, declarator in enumerate([*node.children]):
            if node.field_name_for_child(index) != "declarator":
                continue
            name = _parameter_name_node(declarator)
            if name is not None:
                shadowed.add(_node_text(name, source))
            else:
                shadowed.update(
                    _node_text(child, source)
                    for binding in (declarator, *_named_descendants(declarator))
                    if binding.type == "structured_binding_declarator"
                    for child in binding.named_children
                    if child.type == "identifier"
                )
    source_lines = source.splitlines()
    return tuple(
        replace(call, kind="attribute", base=owner_name)
        if call.target in owner.visibility
        and not any(
            (scope.start_point.row, scope.start_point.column)
            <= (call.lineno - 1, call.col_offset)
            < (scope.end_point.row, scope.end_point.column)
            for scope in nested_scopes
        )
        and (
            (
                call.kind == "name"
                and not call.base
                and call.target not in shadowed
                and not source_lines[call.lineno - 1][call.col_offset :]
                .lstrip()
                .startswith(b"::")
                and not source_lines[call.lineno - 1][: call.col_offset]
                .rstrip()
                .endswith(b"::")
            )
            or (call.kind == "attribute" and call.base == "this")
        )
        else call
        for call in function.calls
    )


def _attach_external_method_owners(
    result: AnalysisResult,
    context: IncludeContext,
    root: Path,
    owner_id: str,
    source_tree: Node,
) -> AnalysisResult:
    """Attach proven owners to qualified definitions without fake class rows.

    Parameters
    ----------
    result : AnalysisResult
        Source-local normalized output.
    context : IncludeContext
        Captured include inputs.
    root : pathlib.Path
        Repository root for declaration identities.
    owner_id : str
        Source-owned identity prefix for callable definitions.
    source_tree : tree_sitter.Node
        Recovered tree used to check lexical call bindings.

    Returns
    -------
    AnalysisResult
        Methods retain source spans and refer to the original header declaration.
        Header owner discovery is skipped when source namespace or alias
        evidence already excludes every requested owner. Callable identities
        still receive the same final disambiguation.
    """
    if not any("::" in function.name for function in result.functions):
        return result
    requested_owners = {
        _qualified_name(_split_qualified_name(function.name)[:-1])
        for function in result.functions
    }
    source_conflicts = {
        _qualified_name(_split_qualified_name(name)[:end])
        for name in _external_owner_alternatives(result)
        for end in range(1, len(_split_qualified_name(name)) + 1)
    }
    # Header alternatives can only add conflicts, never remove source evidence.
    # Include unqualified functions above so mixed inputs retain header lookup.
    owners = (
        {}
        if requested_owners <= source_conflicts
        else _external_method_owners(context, root, result)
    )
    functions: list[FunctionArtifact] = []
    for function in result.functions:
        parts = _split_qualified_name(function.name)
        owner_name = _qualified_name(parts[:-1])
        owner = owners.get(owner_name)
        if owner is None:
            functions.append(function)
            continue
        name = parts[-1]
        visibility = owner.visibility.get(name, set())
        functions.append(
            replace(
                function,
                name=name,
                stable_id=_function_stable_id(owner_id, name, class_name=owner_name),
                is_method=1,
                is_public=next(iter(visibility))
                if len(visibility) == 1
                else function.is_public,
                owner_name=owner_name,
                owner_stable_id=next(iter(owner.stable_ids))
                if len(owner.stable_ids) == 1
                else None,
                calls=_external_member_calls(
                    function, owner_name, owner, context.source, source_tree
                ),
            )
        )
    return replace(
        result, functions=_disambiguate_callable_stable_ids(tuple(functions))
    )


class CppAnalyzer:
    """
    Concrete C++ analyzer for repository indexing.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Creates a configured C++ analyzer.

    Notes
    -----
    This analyzer is backed by `tree-sitter-cpp` and targets deterministic
    structural extraction rather than compilation-complete C++ semantics.
    """

    name = "cpp"
    version = "36"
    discovery_globs: tuple[str, ...] = (
        "*.cpp",
        "*.cc",
        "*.cxx",
        "*.hpp",
        "*.hh",
        "*.hxx",
        "*.ipp",
        "*.h",
    )
    default_coverage_roots: tuple[str, ...] = ("src", "include", "tests")

    def __init__(self) -> None:
        """Initialize default analyzer and header-routing options.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Automatic header detection is enabled by default.
        """
        self._path_filters = AnalyzerPathFilters()
        self._header_language = "auto"
        self._include_search_paths: tuple[Path, ...] = ()
        self._namespace_macro_definitions: tuple[tuple[bytes, bytes], ...] = ()
        self._preprocessor_definitions: dict[bytes, _MacroDefinition | None] | None = (
            None
        )
        self._preprocessor_features: FeatureAnswers = {}
        self._preprocessor_header_queries: dict[str, HeaderQuerySet] = {}
        self._preprocessor_query_profile_fingerprint = plugin_configuration_fingerprint(
            {}
        )
        self._use_leading_comments = True
        self._emit_doxygen_documentation = True
        self._include_system_includes = True
        self._emit_namespaces = True
        self._emit_macros = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the C++ analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for C++ analyzer options.
        """

        return analyzer_json_schema(
            {
                "use_leading_comments": boolean_property(True),
                "emit_doxygen_documentation": boolean_property(True),
                "include_system_includes": boolean_property(True),
                "include_search_paths": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "default": [],
                    "description": (
                        "Ordered include search roots, relative to the repository "
                        "or absolute inside it. Quoted includes search their "
                        "own directory first."
                    ),
                },
                "namespace_macro_definitions": {
                    "type": "object",
                    "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "additionalProperties": {
                        "type": "string",
                        "pattern": "^[A-Za-z_][A-Za-z_0-9]*$",
                    },
                    "default": {},
                    "description": "Explicit identifier bindings for namespace declaration names; no branch selection or general expression expansion.",
                },
                "preprocessor_definitions": {
                    "type": "object",
                    "maxProperties": 4096,
                    "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z_0-9]*$"},
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "boolean"},
                            {
                                "type": "object",
                                "properties": {"defined": {"const": True}},
                                "required": ["defined"],
                                "additionalProperties": False,
                            },
                        ]
                    },
                    "description": "Opt-in bounded captured declaration-macro analysis. Strings are object replacements, true is 1, false is explicitly undefined, and {defined: true} supplies opaque definedness. Missing names remain unknown.",
                },
                "preprocessor_features": {
                    "type": "object",
                    "maxProperties": 4096,
                    "additionalProperties": {"type": "string", "maxLength": 32},
                    "description": "Explicit exact native integer answers for pure compiler feature queries. Source overrides and changed argument macros remain unsupported.",
                },
                "preprocessor_header_queries": header_queries_schema(),
                "emit_namespaces": boolean_property(True),
                "emit_macros": boolean_property(True),
                "header_language": {
                    "type": "string",
                    "enum": ["auto", "c", "cpp"],
                    "default": "auto",
                    "description": "Language selection for ambiguous .h headers.",
                },
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply C++ analyzer configuration.

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
            If header_language is not auto, c or cpp, or include_search_paths
            is not a list of nonempty strings, or namespace_macro_definitions
            is not an identifier mapping. Repository containment is checked
            when analysis inputs are read. Invalid compiler query literals,
            observation identities, ranges or bounds are rejected explicitly.
        """

        self._path_filters = analyzer_path_filters_from_config(config)
        self._header_language = str(config.get("header_language", "auto"))
        if self._header_language not in {"auto", "c", "cpp"}:
            raise ValueError("header_language must be auto, c or cpp")
        search_paths = config.get("include_search_paths", [])
        if not isinstance(search_paths, list) or any(
            not isinstance(item, str) or not item for item in search_paths
        ):
            raise ValueError("include_search_paths must be a list of nonempty strings")
        self._include_search_paths = tuple(Path(item) for item in search_paths)
        self._namespace_macro_definitions = _namespace_bindings_from_config(
            config.get("namespace_macro_definitions", {})
        )
        from .cpp_generated_analysis import preprocessor_definitions

        self._preprocessor_definitions = (
            preprocessor_definitions(config["preprocessor_definitions"])
            if "preprocessor_definitions" in config
            else None
        )
        self._preprocessor_features = feature_answers(
            config.get("preprocessor_features", {}), self._preprocessor_definitions
        )
        self._preprocessor_header_queries = header_query_sets(
            config.get("preprocessor_header_queries", {})
        )
        if self._preprocessor_header_queries and self._preprocessor_definitions is None:
            raise ValueError(
                "header query observations require explicit preprocessor_definitions"
            )
        self._preprocessor_query_profile_fingerprint = plugin_configuration_fingerprint(
            {
                key: value
                for key, value in config.items()
                if key != "preprocessor_header_queries"
            }
        )
        self._use_leading_comments = bool(config.get("use_leading_comments", True))
        self._emit_doxygen_documentation = bool(
            config.get("emit_doxygen_documentation", True)
        )
        self._include_system_includes = bool(
            config.get("include_system_includes", True)
        )
        self._emit_namespaces = bool(config.get("emit_namespaces", True))
        self._emit_macros = bool(config.get("emit_macros", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return C++ analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from C++ artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_cpp:build_analyzer",
            supports=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "namespace",
                "documentation",
            ),
            does_not_support=("variable",),
            mappings={
                "module": "module",
                "class": "type",
                "struct": "type",
                "union": "type",
                "enum": "type",
                "type_alias": "type",
                "function": "callable",
                "method": "callable",
                "namespace": "namespace",
                "macro": "constant",
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
        Decide whether the analyzer accepts a C++ source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file carries a supported C++ suffix.
        """
        return path.suffix in _CPP_SUFFIXES

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported C++ path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when filters allow the path and header routing claims it.
        """

        if not analyzer_path_allowed(path=path, root=root, filters=self._path_filters):
            return False
        if path.suffix != ".h":
            return True
        if self._header_language != "auto":
            return self._header_language == "cpp"
        return _is_cpp_header(path)

    def path_priority(self, path: Path, root: Path) -> int:
        """Prefer this plugin for accepted C++ headers over generic C claims.

        Parameters
        ----------
        path : pathlib.Path
            Already accepted source path.
        root : pathlib.Path
            Repository root supplied by the indexing contract.

        Returns
        -------
        int
            C++ headers have priority one; other paths retain default precedence.
        """
        return 1 if path.suffix == ".h" else 0

    def analysis_input_fingerprint(self, path: Path, root: Path) -> str:
        """Identify literal include inputs using the same snapshot as analysis.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit considered for incremental reuse.
        root : pathlib.Path
            Repository boundary for contained include resolution.

        Returns
        -------
        str
            Dependency identity including header bytes and negative lookups.
        """
        from .cpp_generated_analysis import captured_identity

        return validate_analysis_input_fingerprint(
            captured_identity(
                read_include_context(
                    path, root, include_paths=self._include_search_paths
                ),
                self.configuration_fingerprint,
            )
        )

    def analysis_input_fingerprint_matches(
        self, path: Path, root: Path, expected: str
    ) -> bool:
        """Check captured input content and resolutions without reparsing C++.

        Parameters
        ----------
        path : pathlib.Path
            Translation unit being checked.
        root : pathlib.Path
            Repository boundary.
        expected : str
            Captured versioned include-input manifest.

        Returns
        -------
        bool
            Whether source/header bytes and resolution outcomes remain current.
        """
        try:
            payload = json.loads(expected)
        except ValueError:
            return False
        return (
            isinstance(payload, dict)
            and payload.get("generated_provenance_version") == 1
            and payload.get("configuration_fingerprint")
            == self.configuration_fingerprint
            and include_identity_matches(
                path,
                root,
                json.dumps(
                    {
                        key: value
                        for key, value in payload.items()
                        if key != "generated_provenance_version"
                    }
                ),
                include_paths=self._include_search_paths,
            )
        )

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one C++ source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            C++ source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        context = read_include_context(
            path, root, include_paths=self._include_search_paths
        )
        if self._preprocessor_definitions is not None:
            from .cpp_generated_analysis import analyze_generated_file

            try:
                return analyze_generated_file(self, path, root, context)
            except ValueError as error:
                result = self._analyze_captured_file(path, root, context)
                status = result.status
                diagnostic = AnalysisDiagnostic(
                    category="macro_context", message=str(error)
                )
                return replace(
                    result,
                    index_symbols=False,
                    status=AnalysisStatus(
                        grammar="tree-sitter-cpp",
                        target_contract={"language": "cpp"},
                        diagnostics=(
                            *(status.diagnostics if status is not None else ()),
                            diagnostic,
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
        return self._analyze_captured_file(path, root, context)

    def _analyze_captured_file(
        self,
        path: Path,
        root: Path,
        context: IncludeContext,
        *,
        syntax_root: Node | None = None,
        comment_source: bytes | None = None,
    ) -> AnalysisResult:
        """Extract ordinary syntax from an explicitly supplied immutable snapshot.

        Parameters
        ----------
        path, root : pathlib.Path
            Original file and trusted repository root.
        context : IncludeContext
            Exact source/header bytes, possibly a generated parser projection.
        syntax_root : SyntaxNode or None, optional
            Statement-only syntax already mapped to the original source buffer.
        comment_source : bytes or None, optional
            Unmasked source in the same coordinate space for physical attachment.

        Returns
        -------
        AnalysisResult
            Ordinary normalized extraction before generated coordinate repair.
        """
        source = context.source
        root_node = (
            syntax_root
            if syntax_root is not None
            else _parse_with_namespace_bindings(
                source,
                bindings=self._namespace_macro_definitions,
                included_sources=tuple(
                    (header.source, header.available_after)
                    for header in context.headers
                ),
            )
        )
        comment_root = root_node
        if comment_source is not None:
            comment_root = _parse_with_namespace_bindings(
                comment_source,
                bindings=self._namespace_macro_definitions,
                included_sources=tuple(
                    (header.source, header.available_after)
                    for header in context.headers
                ),
            )
        comment_bytes = source if comment_source is None else comment_source
        module_comment = (
            _leading_module_comment(comment_root, comment_bytes)
            if self._use_leading_comments
            else None
        )
        module_doxygen = _leading_module_doxygen(comment_root, comment_bytes)
        module_name = _module_name_for_path(path, root)
        module_stable_id = _module_stable_id(path, root)
        owner_id = _symbol_owner_id(path, root)
        known_class_names = _collect_known_class_names(root_node.children, source)
        builder = _CppAnalysisBuilder(
            source=source,
            root=root_node,
            owner_id=owner_id,
            known_class_names=known_class_names,
            comment_maps=(
                source_comment_maps(comment_root, comment_bytes)
                if comment_source is not None
                else None
            ),
        )
        result = builder.build(
            source_path=path,
            module_name=module_name,
            module_stable_id=module_stable_id,
            module_docstring=module_comment,
        )
        result = _attach_external_method_owners(
            result, context, root, owner_id, root_node
        )
        if not self._use_leading_comments:
            result = replace(
                result,
                module=replace(result.module, docstring=None, has_docstring=0),
                classes=tuple(replace(cls, docstring=None) for cls in result.classes),
                functions=tuple(
                    replace(function, docstring=None) for function in result.functions
                ),
                declarations=tuple(
                    replace(declaration, docstring=None)
                    for declaration in result.declarations
                ),
            )
        if not self._include_system_includes:
            result = replace(
                result,
                imports=tuple(
                    item for item in result.imports if item.kind != "include_system"
                ),
            )
        if not self._emit_namespaces:
            result = replace(
                result,
                declarations=tuple(
                    declaration
                    for declaration in result.declarations
                    if declaration.kind != "namespace"
                ),
            )
        if not self._emit_macros:
            result = replace(
                result,
                declarations=tuple(
                    declaration
                    for declaration in result.declarations
                    if declaration.kind != "macro"
                ),
            )
        return replace(
            result,
            documentation=(
                _documentation_artifacts(
                    path=path,
                    analysis=result,
                    module_doxygen=module_doxygen,
                    doxygen_by_lineno=builder.doxygen_by_lineno,
                )
                if self._emit_doxygen_documentation
                else ()
            ),
            index_symbols=not root_node.has_error,
            status=tree_sitter_recovery_status(
                language="cpp", has_error=root_node.has_error
            ),
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party C++ analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        First-party C++ analyzer instance.
    """
    return CppAnalyzer()
