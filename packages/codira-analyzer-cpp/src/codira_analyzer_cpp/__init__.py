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
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

from tree_sitter import Language, Node, Parser
from tree_sitter_cpp import language

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.models import (
    AnalysisResult,
    CallSite,
    ClassArtifact,
    DeclarationArtifact,
    DeclarationKind,
    DocumentationArtifact,
    DocumentationKind,
    EnumMemberArtifact,
    FunctionArtifact,
    ImportArtifact,
    ImportKind,
    ModuleArtifact,
)

_CPP_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp"}
_LANGUAGE = Language(language())
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
_CPP_SYSTEM_FUNCTIONS = frozenset(
    {
        "begin",
        "emplace_back",
        "end",
        "make_pair",
        "make_shared",
        "move",
        "printf",
        "push_back",
        "size",
        "sort",
        "swap",
    }
)
_CPP_MACROS = frozenset(
    {
        "ASSERT_EQ",
        "ASSERT_FALSE",
        "ASSERT_TRUE",
        "EXPECT_EQ",
        "EXPECT_FALSE",
        "EXPECT_TRUE",
        "Py_DECREF",
        "Py_INCREF",
    }
)


@dataclass(frozen=True)
class _PendingFunction:
    """Function candidate awaiting final ownership resolution."""

    artifact: FunctionArtifact
    class_name: str | None
    is_definition: bool


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
        key = (pending.artifact.stable_id, pending.artifact.parameters)
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


def _new_parser() -> Parser:
    """
    Create a parser configured for the C++ grammar.

    Parameters
    ----------
    None

    Returns
    -------
    tree_sitter.Parser
        Parser configured for ``tree-sitter-cpp``.
    """
    return Parser(_LANGUAGE)


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
    Derive the logical module name for one C++ source path.

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
    Build the durable identity for one C++ module.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable C++ module identity.
    """
    return f"cpp:module:{path.relative_to(root).as_posix()}"


def _symbol_owner_id(path: Path, root: Path) -> str:
    """
    Build the file-scoped owner identity for C++ symbols.

    Parameters
    ----------
    path : pathlib.Path
        Source path being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Repo-relative owner identity that preserves the source suffix.
    """
    return path.relative_to(root).as_posix()


def _class_stable_id(owner_id: str, class_name: str) -> str:
    """
    Build the durable identity for one C++ class.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    class_name : str
        Qualified class name.

    Returns
    -------
    str
        Durable C++ class identity.
    """
    return f"cpp:class:{owner_id}:{class_name}"


def _function_stable_id(
    owner_id: str,
    function_name: str,
    *,
    class_name: str | None = None,
) -> str:
    """
    Build the durable identity for one C++ callable.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    function_name : str
        Callable name to persist.
    class_name : str | None, optional
        Owning class name for method artifacts.

    Returns
    -------
    str
        Durable C++ function or method identity.
    """
    if class_name is None:
        return f"cpp:function:{owner_id}:{function_name}"
    return f"cpp:method:{owner_id}:{class_name}.{function_name}"


def _declaration_stable_id(
    owner_id: str,
    kind: DeclarationKind,
    declaration_name: str,
) -> str:
    """
    Build the durable identity for one C++ declaration artifact.

    Parameters
    ----------
    owner_id : str
        File-scoped owner identity preserving the source suffix.
    kind : codira.models.DeclarationKind
        Stable declaration classifier.
    declaration_name : str
        Exposed declaration name.

    Returns
    -------
    str
        Durable C++ declaration identity.
    """
    return f"cpp:{kind}:{owner_id}:{declaration_name}"


def _enum_member_stable_id(
    owner_id: str,
    enum_name: str,
    ordinal: int,
) -> str:
    """
    Build the durable identity for one C++ enum member declaration.

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
        Durable C++ enum-member identity.
    """
    return f"cpp:enum_member:{owner_id}:{enum_name}:{ordinal}"


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


def _normalize_signature(text: str) -> str:
    """
    Collapse one signature or declaration snippet into stable whitespace.

    Parameters
    ----------
    text : str
        Raw source text snippet.

    Returns
    -------
    str
        Whitespace-normalized text.
    """
    return " ".join(text.split())


def _qualified_name(parts: Sequence[str]) -> str:
    """
    Join one namespace or class path into C++ qualified text.

    Parameters
    ----------
    parts : collections.abc.Sequence[str]
        Qualified-name path components.

    Returns
    -------
    str
        `::`-joined qualified name.
    """
    return "::".join(part for part in parts if part)


def _split_qualified_name(text: str) -> tuple[str, ...]:
    """
    Split one C++ qualified identifier into components.

    Parameters
    ----------
    text : str
        Raw qualified identifier text.

    Returns
    -------
    tuple[str, ...]
        Non-empty qualified-name components.
    """
    normalized = text.replace(" ", "")
    return tuple(part for part in normalized.split("::") if part)


def _cpp_external_target_kind(base: str, target: str) -> str:
    """
    Classify one C++ call target for unresolved graph rendering.

    Parameters
    ----------
    base : str
        Static receiver or namespace qualifier.
    target : str
        Call target token.

    Returns
    -------
    str
        Analyzer-owned external target classifier.
    """
    if target in _CPP_MACROS or target.isupper():
        return "C++:<macro>"
    if base == "std" or base.startswith("std::") or target in _CPP_SYSTEM_FUNCTIONS:
        return "C++:<system-header>"
    return "C++:<external>"


def _comment_to_summary(text: str) -> str | None:
    """
    Normalize one raw C++ comment block into summary text.

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
    children: Sequence[Node], source: bytes
) -> dict[int, tuple[str, int, int | None]]:
    """
    Map declaration start lines to nearby leading Doxygen comments.

    Parameters
    ----------
    children : collections.abc.Sequence[tree_sitter.Node]
        Sibling nodes that may carry leading comments.
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
    previous_non_comment_end_row: int | None = None

    for child in children:
        if child.type == "comment":
            if previous_non_comment_end_row != child.start_point.row:
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
                attached[child.start_point.row + 1] = pending_comment
            pending_comment = None
            pending_end_row = None
        previous_non_comment_end_row = child.end_point.row

    return attached


def _attached_comment_map(children: Sequence[Node], source: bytes) -> dict[int, str]:
    """
    Map declaration start bytes to nearby leading comment summaries.

    Parameters
    ----------
    children : collections.abc.Sequence[tree_sitter.Node]
        Sibling nodes that may carry leading comments.
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
    previous_non_comment_end_row: int | None = None

    for child in children:
        if child.type == "comment":
            if previous_non_comment_end_row != child.start_point.row:
                pending_comment = _comment_to_summary(_node_text(child, source))
                pending_end_row = child.end_point.row
            continue

        if pending_comment is not None and pending_end_row is not None:
            if child.start_point.row - pending_end_row <= 2:
                attached[child.start_byte] = pending_comment
            pending_comment = None
            pending_end_row = None
        previous_non_comment_end_row = child.end_point.row

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
    for child in reversed(node.named_children):
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
        Namespace path components in declaration order.
    """
    for child in node.named_children:
        if child.type in {"namespace_identifier", "nested_namespace_specifier"}:
            return _split_qualified_name(_node_text(child, source))
    return ()


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
    }:
        direct_name = _node_text(direct_declarator, source)
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
    }:
        return _node_text(node, source)

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
        if child.type != "parameter_declaration":
            continue
        declarator = child.child_by_field_name("declarator")
        if declarator is None:
            continue
        name = _unwrap_declarator_name(declarator, source)
        if name is not None:
            parameters.append(name.split("::")[-1])
    return tuple(parameters)


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
            external_target_kind=_cpp_external_target_kind("", target),
            external_target_name=target,
        )

    if function_node.type == "qualified_identifier":
        target_parts = _split_qualified_name(_node_text(function_node, source))
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
        Call records in deterministic source order.
    """
    if body is None:
        return ()

    calls: list[CallSite] = []
    for node in _named_descendants(body):
        if node.type != "call_expression":
            continue
        call = _call_site_from_expression(node, source)
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
    Locate a function declarator nested under one declaration node.

    Parameters
    ----------
    node : tree_sitter.Node
        Declaration-like node to inspect.

    Returns
    -------
    tree_sitter.Node | None
        Nested `function_declarator` when present.
    """
    if node.type == "function_declarator":
        return node
    if _find_parameter_list(node) is not None:
        return node
    for child in node.named_children:
        declarator = _find_function_declarator(child)
        if declarator is not None:
            return declarator
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
        Declared class name when present.
    """
    name_node = next(
        (
            child
            for child in node.named_children
            if child.type in {"type_identifier", "identifier"}
        ),
        None,
    )
    if name_node is None:
        return None
    return _node_text(name_node, source)


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
        Declared type name when present.
    """
    for child in node.named_children:
        if child.type in {"type_identifier", "identifier"}:
            return _node_text(child, source)
    return None


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
    signature_end = body.start_byte if body is not None else signature_node.end_byte
    signature = _decode_source_text(
        source[signature_node.start_byte : signature_end]
    ).strip()

    artifact = FunctionArtifact(
        name=method_name if class_name is not None else resolved_name,
        stable_id=_function_stable_id(
            owner_id,
            method_name if class_name is not None else resolved_name,
            class_name=class_name,
        ),
        lineno=signature_node.start_point.row + 1,
        end_lineno=body.end_point.row + 1 if body is not None else None,
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
        calls=_extract_calls(body, source),
        callable_refs=(),
    )
    return _PendingFunction(
        artifact=artifact,
        class_name=class_name,
        is_definition=body is not None,
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
    for child in children:
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

        if child.type != "class_specifier":
            continue
        class_name = _class_name_from_specifier(child, source)
        if class_name is None:
            continue
        known.add(_qualified_name((*namespace, class_name)))
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
    """

    def __init__(
        self,
        *,
        source: bytes,
        root: Node,
        owner_id: str,
        known_class_names: set[str],
    ) -> None:
        self.source = source
        self.root = root
        self.owner_id = owner_id
        self.known_class_names = known_class_names
        self.class_builders: dict[str, _ClassBuilder] = {}
        self.functions_by_key: dict[tuple[str, tuple[str, ...]], _PendingFunction] = {}
        self.declarations_by_id: dict[str, DeclarationArtifact] = {}
        self.doxygen_by_lineno: dict[int, tuple[str, int, int | None]] = {}

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
            key = (pending.artifact.stable_id, pending.artifact.parameters)
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
        Record one class declaration and its in-class methods.

        Parameters
        ----------
        node : tree_sitter.Node
            Class-specifier node.
        namespace : collections.abc.Sequence[str]
            Active namespace path.
        docstring : str | None
            Attached docstring when present.

        Returns
        -------
        None
            Class and method artifacts are stored in place.
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
        builder = self._ensure_class_builder(
            qualified_name=qualified_name,
            lineno=node.start_point.row + 1,
            end_lineno=node.end_point.row + 1,
            docstring=docstring,
        )
        if field_list is None:
            return

        current_public = any(child.type == "struct" for child in node.children)
        attached_comments = _attached_comment_map(field_list.children, self.source)
        self.doxygen_by_lineno.update(
            _attached_doxygen_comment_map(field_list.children, self.source)
        )
        for child in field_list.children:
            if child.type == "access_specifier":
                current_public = _node_text(child, self.source) in {
                    "public",
                    "protected",
                }
                continue

            child_docstring = attached_comments.get(child.start_byte)
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
        if node.type == "namespace_definition":
            self._handle_namespace(node, namespace=namespace, docstring=docstring)
            return
        if node.type == "class_specifier":
            self._handle_class_specifier(node, namespace=namespace, docstring=docstring)
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
    Build one Doxygen documentation artifact for a C++ owner.

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
    kind : codira.models.DocumentationKind, optional
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


def _append_attached_documentation_artifact(
    artifacts: list[DocumentationArtifact],
    *,
    path: Path,
    owner_stable_id: str,
    owner_kind: str,
    title: str,
    owner_lineno: int,
    doxygen_by_lineno: dict[int, tuple[str, int, int | None]],
) -> None:
    """
    Append one owner-attached Doxygen artifact when a match exists.

    Parameters
    ----------
    artifacts : list[codira.models.DocumentationArtifact]
        Mutable documentation artifact accumulator.
    path : pathlib.Path
        Source file that owns the documentation artifact.
    owner_stable_id : str
        Stable identity of the documented owner.
    owner_kind : str
        Stable classifier of the documented owner.
    title : str
        Human-readable owner title.
    owner_lineno : int
        Source line where the documented owner starts.
    doxygen_by_lineno : dict[int, tuple[str, int, int | None]]
        Attached Doxygen documentation keyed by owner start line.

    Returns
    -------
    None
        The accumulator is updated in place when documentation exists.
    """
    attached = doxygen_by_lineno.get(owner_lineno)
    if attached is None:
        return
    text, lineno, end_lineno = attached
    artifacts.append(
        _documentation_artifact(
            path=path,
            owner_stable_id=owner_stable_id,
            owner_kind=owner_kind,
            title=title,
            text=text,
            lineno=lineno,
            end_lineno=end_lineno,
        )
    )


def _documentation_artifacts(
    *,
    path: Path,
    analysis: AnalysisResult,
    module_doxygen: tuple[str, int, int | None] | None,
    doxygen_by_lineno: dict[int, tuple[str, int, int | None]],
) -> tuple[DocumentationArtifact, ...]:
    """
    Build C++ Doxygen documentation artifacts for module and declaration owners.

    Parameters
    ----------
    path : pathlib.Path
        C++ source path being analyzed.
    analysis : codira.models.AnalysisResult
        Analyzer result whose owners may have attached Doxygen documentation.
    module_doxygen : tuple[str, int, int | None] | None
        Leading Doxygen module documentation and source coordinates.
    doxygen_by_lineno : dict[int, tuple[str, int, int | None]]
        Attached Doxygen documentation keyed by owner start line.

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
                owner_stable_id=analysis.module.stable_id,
                owner_kind="module",
                title=analysis.module.name,
                text=text,
                lineno=lineno,
                end_lineno=end_lineno,
                kind="module",
            )
        )

    for class_artifact in analysis.classes:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=class_artifact.stable_id,
            owner_kind="class",
            title=class_artifact.name,
            owner_lineno=class_artifact.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
        )
        for method in class_artifact.methods:
            _append_attached_documentation_artifact(
                artifacts,
                path=path,
                owner_stable_id=method.stable_id,
                owner_kind="method",
                title=method.name,
                owner_lineno=method.lineno,
                doxygen_by_lineno=doxygen_by_lineno,
            )

    for function in analysis.functions:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=function.stable_id,
            owner_kind="function",
            title=function.name,
            owner_lineno=function.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
        )

    for declaration in analysis.declarations:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=declaration.stable_id,
            owner_kind=declaration.kind,
            title=declaration.name,
            owner_lineno=declaration.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
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
    for child in root.children:
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


class CppAnalyzer:
    """
    Concrete C++ analyzer for repository indexing.

    Parameters
    ----------
    None

    Notes
    -----
    This analyzer is backed by `tree-sitter-cpp` and targets deterministic
    structural extraction rather than compilation-complete C++ semantics.
    """

    name = "cpp"
    version = "4"
    discovery_globs: tuple[str, ...] = (
        "*.cpp",
        "*.cc",
        "*.cxx",
        "*.hpp",
        "*.hh",
        "*.hxx",
        "*.ipp",
    )

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
                "include_local": "import",
                "include_system": "import",
                "doxygen": "documentation",
            },
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
        source = path.read_bytes()
        root_node = _new_parser().parse(source).root_node
        module_comment = _leading_module_comment(root_node, source)
        module_doxygen = _leading_module_doxygen(root_node, source)
        module_name = _module_name_for_path(path, root)
        module_stable_id = _module_stable_id(path, root)
        owner_id = _symbol_owner_id(path, root)
        known_class_names = _collect_known_class_names(root_node.children, source)
        builder = _CppAnalysisBuilder(
            source=source,
            root=root_node,
            owner_id=owner_id,
            known_class_names=known_class_names,
        )
        result = builder.build(
            source_path=path,
            module_name=module_name,
            module_stable_id=module_stable_id,
            module_docstring=module_comment,
        )
        return replace(
            result,
            documentation=_documentation_artifacts(
                path=path,
                analysis=result,
                module_doxygen=module_doxygen,
                doxygen_by_lineno=builder.doxygen_by_lineno,
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
