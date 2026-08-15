"""Normalized Tree-sitter syntax support for the Python analyzer.

Responsibilities
----------------
- Construct isolated parsers for the bundled Python grammar.
- Normalize provider nodes into Codira-owned kinds and byte-based spans.
- Report error and missing syntax nodes without exposing grammar internals.

Design principles
-----------------
The adapter retains no parser state between calls and does not use the host
``ast`` module.  Tree-sitter node names are confined to this module so later
extractors depend only on the normalized contract.

Architectural role
------------------
This module belongs to the Python analyzer package.  It is intentionally not a
core dependency because grammar selection is analyzer-specific.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from tree_sitter import Language, Node, Parser
from tree_sitter_python import language

__all__ = [
    "SyntaxDiagnostic",
    "SyntaxDiagnosticKind",
    "SyntaxKind",
    "SyntaxNode",
    "SyntaxTree",
    "module_docstring_location",
    "parse_python_artifacts",
    "parse_python_source",
]


class SyntaxKind(StrEnum):
    """Codira-owned categories for Python syntax nodes."""

    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    DECORATED = "decorated"
    IMPORT = "import"
    IMPORT_FROM = "import_from"
    ASSIGNMENT = "assignment"
    ANNOTATED_ASSIGNMENT = "annotated_assignment"
    TYPE_ALIAS = "type_alias"
    PARAMETERS = "parameters"
    RETURN = "return"
    RAISE = "raise"
    IF = "if"
    CALL = "call"
    ATTRIBUTE = "attribute"
    IDENTIFIER = "identifier"
    STRING = "string"
    INTEGER = "integer"
    COMMENT = "comment"
    OTHER = "other"


class SyntaxDiagnosticKind(StrEnum):
    """Normalized classes of recoverable parser diagnostics."""

    ERROR = "error"
    MISSING = "missing"


@dataclass(frozen=True)
class SyntaxNode:
    """One provider-neutral syntax node with byte-based source locations.

    Parameters
    ----------
    kind : SyntaxKind
        Codira-owned node category.
    start_byte, end_byte : int
        Half-open UTF-8 byte range in the original source.
    start_line, end_line : int
        One-based source line range.
    start_column, end_column : int
        Zero-based UTF-8 byte columns within their respective lines.
    children : tuple[SyntaxNode, ...]
        Named descendants in deterministic source order.
    """

    kind: SyntaxKind
    start_byte: int
    end_byte: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    children: tuple[SyntaxNode, ...]


@dataclass(frozen=True)
class SyntaxDiagnostic:
    """One normalized error-recovery observation from parsing source.

    Parameters
    ----------
    kind : SyntaxDiagnosticKind
        Whether the parser encountered invalid input or inserted a missing node.
    start_byte, end_byte : int
        Half-open UTF-8 byte range associated with the recovery point.
    start_line, end_line : int
        One-based source line range.
    start_column, end_column : int
        Zero-based UTF-8 byte columns within their respective lines.
    """

    kind: SyntaxDiagnosticKind
    start_byte: int
    end_byte: int
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class SyntaxTree:
    """One normalized Python syntax tree and its recovery diagnostics."""

    root: SyntaxNode
    diagnostics: tuple[SyntaxDiagnostic, ...]


_LANGUAGE = Language(language())
_NODE_KINDS = {
    "module": SyntaxKind.MODULE,
    "class_definition": SyntaxKind.CLASS,
    "function_definition": SyntaxKind.FUNCTION,
    "async_function_definition": SyntaxKind.ASYNC_FUNCTION,
    "decorated_definition": SyntaxKind.DECORATED,
    "import_statement": SyntaxKind.IMPORT,
    "import_from_statement": SyntaxKind.IMPORT_FROM,
    "assignment": SyntaxKind.ASSIGNMENT,
    "augmented_assignment": SyntaxKind.ASSIGNMENT,
    "annotated_assignment": SyntaxKind.ANNOTATED_ASSIGNMENT,
    "type_alias_statement": SyntaxKind.TYPE_ALIAS,
    "parameters": SyntaxKind.PARAMETERS,
    "return_statement": SyntaxKind.RETURN,
    "raise_statement": SyntaxKind.RAISE,
    "if_statement": SyntaxKind.IF,
    "call": SyntaxKind.CALL,
    "attribute": SyntaxKind.ATTRIBUTE,
    "identifier": SyntaxKind.IDENTIFIER,
    "string": SyntaxKind.STRING,
    "integer": SyntaxKind.INTEGER,
    "comment": SyntaxKind.COMMENT,
}


def _new_parser() -> Parser:
    """Create one Python parser without sharing mutable parser state.

    Returns
    -------
    tree_sitter.Parser
        A parser configured for the Python grammar.
    """
    return Parser(_LANGUAGE)


def _normalized_node(node: Node) -> SyntaxNode:
    """Convert one Tree-sitter node into the provider-neutral contract.

    Parameters
    ----------
    node : tree_sitter.Node
        Provider node to normalize.

    Returns
    -------
    SyntaxNode
        Node with Codira-owned kind, byte spans, and named descendants.
    """
    start = node.start_point
    end = node.end_point
    return SyntaxNode(
        kind=_NODE_KINDS.get(node.type, SyntaxKind.OTHER),
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_line=start.row + 1,
        start_column=start.column,
        end_line=end.row + 1,
        end_column=end.column,
        children=tuple(_normalized_node(child) for child in node.named_children),
    )


def _diagnostics(node: Node) -> tuple[SyntaxDiagnostic, ...]:
    """Return deterministic recovery diagnostics for a syntax subtree.

    Parameters
    ----------
    node : tree_sitter.Node
        Root node whose descendants should be inspected.

    Returns
    -------
    tuple[SyntaxDiagnostic, ...]
        Error and missing-node diagnostics sorted by location and kind.
    """
    collected: list[SyntaxDiagnostic] = []
    pending = [node]
    while pending:
        current = pending.pop()
        diagnostic_kind: SyntaxDiagnosticKind | None = None
        if current.is_error:
            diagnostic_kind = SyntaxDiagnosticKind.ERROR
        elif current.is_missing:
            diagnostic_kind = SyntaxDiagnosticKind.MISSING
        if diagnostic_kind is not None:
            start = current.start_point
            end = current.end_point
            collected.append(
                SyntaxDiagnostic(
                    kind=diagnostic_kind,
                    start_byte=current.start_byte,
                    end_byte=current.end_byte,
                    start_line=start.row + 1,
                    start_column=start.column,
                    end_line=end.row + 1,
                    end_column=end.column,
                )
            )
        pending.extend(reversed(current.children))
    return tuple(
        sorted(
            collected,
            key=lambda item: (
                item.start_byte,
                item.end_byte,
                item.kind.value,
            ),
        )
    )


def parse_python_source(source: str | bytes) -> SyntaxTree:
    """Parse Python source independently of the host ``ast`` implementation.

    Parameters
    ----------
    source : str | bytes
        Source text or its exact UTF-8 byte representation.

    Returns
    -------
    SyntaxTree
        Provider-neutral tree with byte spans and deterministic diagnostics.
    """
    source_bytes = source.encode("utf-8") if isinstance(source, str) else source
    root = _new_parser().parse(source_bytes).root_node
    return SyntaxTree(root=_normalized_node(root), diagnostics=_diagnostics(root))


def _text(node: Node | None, source: bytes) -> str:
    """Decode one syntax-node byte range as UTF-8 source text.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Node whose source range should be decoded.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    str
        Decoded source text, or an empty string when ``node`` is absent.
    """
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8")


def _line(node: Node) -> int:
    """Return one node's one-based source line.

    Parameters
    ----------
    node : tree_sitter.Node
        Node whose start point should be converted.

    Returns
    -------
    int
        One-based source line number.
    """
    return node.start_point.row + 1


def _module_name(path: Path, root: Path) -> str:
    """Derive the import-style module name for one source path.

    Parameters
    ----------
    path : pathlib.Path
        Python source file path.
    root : pathlib.Path
        Repository root used for relative resolution.

    Returns
    -------
    str
        Dotted module name without an ``__init__`` suffix.
    """
    parts = list(path.with_suffix("").relative_to(root).parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _attribute_path(node: Node | None, source: bytes) -> str | None:
    """Return a static dotted path represented by a syntax expression.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Expression node to inspect.
    source : bytes
        UTF-8 source bytes owning ``node``.

    Returns
    -------
    str | None
        Dotted identifier path, or ``None`` for dynamic expressions.
    """
    if node is None:
        return None
    if node.type == "identifier":
        return _text(node, source)
    if node.type == "attribute":
        object_node = node.child_by_field_name("object")
        attribute_node = node.child_by_field_name("attribute")
        prefix = _attribute_path(object_node, source)
        name = _text(attribute_node, source)
        return f"{prefix}.{name}" if prefix and name else None
    return None


def _string_value(node: Node | None, source: bytes) -> str | None:
    """Decode a simple Python string literal for documentation extraction.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Candidate string node.
    source : bytes
        UTF-8 source bytes owning ``node``.

    Returns
    -------
    str | None
        Literal content when the node is a string, otherwise ``None``.
    """
    if node is None or node.type != "string":
        return None
    raw = _text(node, source)
    match = re.match(r"(?is)^[rubf]*('''|\"\"\"|'|\")", raw)
    if match is None:
        return None
    quote = match.group(1)
    if not raw.endswith(quote):
        return None
    body = raw[match.end() : -len(quote)]
    return bytes(body, "utf-8").decode("unicode_escape")


def _docstring(body: Node | None, source: bytes) -> tuple[str | None, Node | None]:
    """Return the leading string expression from one statement block.

    Parameters
    ----------
    body : tree_sitter.Node | None
        Module or block node whose first statement may be a docstring.
    source : bytes
        UTF-8 source bytes owning ``body``.

    Returns
    -------
    tuple[str | None, tree_sitter.Node | None]
        Decoded documentation text and its string node when present.
    """
    if body is None:
        return (None, None)
    children = tuple(child for child in body.named_children if child.type != "comment")
    if not children or children[0].type != "expression_statement":
        return (None, None)
    value = children[0].named_children[0] if children[0].named_children else None
    return (_string_value(value, source), value)


def _parameter_name(node: Node, source: bytes) -> str | None:
    """Return the declared name from one Tree-sitter parameter node.

    Parameters
    ----------
    node : tree_sitter.Node
        Parameter node to inspect.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    str | None
        Declared identifier, or ``None`` for a separator or unsupported node.
    """
    if node.type == "identifier":
        return _text(node, source)
    name = node.child_by_field_name("name")
    if name is not None:
        return _text(name, source)
    identifiers = [child for child in node.named_children if child.type == "identifier"]
    return _text(identifiers[0], source) if identifiers else None


def _signature(function: Node, source: bytes) -> tuple[str, list[str]]:
    """Extract the legacy simplified callable signature and parameters.

    Parameters
    ----------
    function : tree_sitter.Node
        Function-definition node to inspect.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    tuple[str, list[str]]
        Simplified signature and logical parameter names.
    """
    name = _text(function.child_by_field_name("name"), source)
    parameters = function.child_by_field_name("parameters")
    if parameters is None:
        return (f"{name}()", [])
    logical_names: list[str] = []
    signature_names: list[str] = []
    positional_only = False
    keyword_only = False
    for parameter in parameters.named_children:
        if parameter.type == "positional_separator":
            positional_only = False
            signature_names.clear()
            continue
        if parameter.type == "keyword_separator":
            keyword_only = True
            continue
        parameter_name = _parameter_name(parameter, source)
        if parameter_name is None:
            continue
        if parameter_name not in {"self", "cls"}:
            logical_names.append(parameter_name)
        prefix = (
            "**"
            if parameter.type == "dictionary_splat_pattern"
            else "*"
            if parameter.type == "list_splat_pattern"
            else ""
        )
        if not positional_only and not keyword_only:
            signature_names.append(f"{prefix}{parameter_name}")
        elif prefix:
            signature_names.append(f"{prefix}{parameter_name}")
    return (f"{name}({', '.join(signature_names)})", logical_names)


def _decorators(wrapper: Node | None, source: bytes) -> list[str]:
    """Extract dotted decorator paths from a decorated definition.

    Parameters
    ----------
    wrapper : tree_sitter.Node | None
        Decorated-definition wrapper, if one owns the callable.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    list[str]
        Decorator paths in declaration order.
    """
    if wrapper is None:
        return []
    result: list[str] = []
    for child in wrapper.named_children:
        if child.type != "decorator":
            continue
        candidate = _text(child, source).lstrip("@").strip().split("(", 1)[0]
        if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", candidate):
            result.append(candidate)
    return result


def _local_nodes(node: Node) -> tuple[Node, ...]:
    """Return descendants within one callable while excluding nested scopes.

    Parameters
    ----------
    node : tree_sitter.Node
        Function-definition node whose body should be traversed.

    Returns
    -------
    tuple[tree_sitter.Node, ...]
        Nodes belonging only to the function's execution scope.
    """
    collected: list[Node] = []
    pending = list(reversed(node.named_children))
    excluded = {
        "function_definition",
        "async_function_definition",
        "class_definition",
        "lambda",
    }
    while pending:
        current = pending.pop()
        if current.type in excluded:
            continue
        collected.append(current)
        pending.extend(reversed(current.named_children))
    return tuple(collected)


def _reference(
    node: Node | None, source: bytes, ref_kind: str
) -> dict[str, Any] | None:
    """Build one callable-reference record from a direct expression node.

    Parameters
    ----------
    node : tree_sitter.Node | None
        Identifier or static attribute expression to classify.
    source : bytes
        UTF-8 source bytes owning ``node``.
    ref_kind : str
        Stable context category for the direct callable value.

    Returns
    -------
    dict[str, typing.Any] | None
        Callable-reference mapping, or ``None`` for non-static expressions.
    """
    if node is None:
        return None
    if node.type == "identifier":
        return {
            "kind": "name",
            "target": _text(node, source),
            "lineno": _line(node),
            "col_offset": node.start_point.column,
            "ref_kind": ref_kind,
        }
    dotted = _attribute_path(node, source)
    if dotted and "." in dotted:
        base, target = dotted.rsplit(".", 1)
        return {
            "kind": "attribute",
            "base": base,
            "target": target,
            "lineno": _line(node),
            "col_offset": node.start_point.column,
            "ref_kind": ref_kind,
        }
    return None


def _calls_and_refs(
    function: Node, source: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract deterministic call-site and callable-reference records.

    Parameters
    ----------
    function : tree_sitter.Node
        Function-definition node to inspect.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    tuple[list[dict[str, Any]], list[dict[str, Any]]]
        Ordered call-site and direct callable-reference mappings.
    """
    calls: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for node in _local_nodes(function):
        if node.type == "call":
            callee = node.child_by_field_name("function")
            dotted = _attribute_path(callee, source)
            if callee is not None and callee.type == "identifier":
                calls.append(
                    {
                        "kind": "name",
                        "target": _text(callee, source),
                        "lineno": _line(callee),
                        "col_offset": callee.start_point.column,
                    }
                )
            elif callee is not None and callee.type == "attribute":
                target = _text(callee.child_by_field_name("attribute"), source)
                base = dotted.rsplit(".", 1)[0] if dotted and "." in dotted else ""
                calls.append(
                    {
                        "kind": "attribute",
                        "base": base,
                        "target": target,
                        "lineno": callee.end_point.row + 1,
                        "col_offset": callee.end_point.column - len(target),
                    }
                )
            else:
                calls.append(
                    {
                        "kind": "unresolved",
                        "target": "",
                        "lineno": _line(node),
                        "col_offset": node.start_point.column,
                    }
                )
        ref_kind = {
            "assignment": "assignment_value",
            "annotated_assignment": "assignment_value",
            "return_statement": "return_value",
        }.get(node.type)
        value = (
            node.child_by_field_name("right")
            or node.child_by_field_name("value")
            or node.child_by_field_name("argument")
        )
        if value is None and node.type == "return_statement" and node.named_children:
            value = node.named_children[-1]
        if ref_kind:
            ref = _reference(value, source, ref_kind)
            if ref is not None:
                refs.append(ref)
        if node.type == "dictionary":
            for pair in node.named_children:
                ref = _reference(
                    pair.child_by_field_name("value"), source, "mapping_value"
                )
                if ref is not None:
                    refs.append(ref)
        if node.type in {"list", "tuple", "set"}:
            for value_node in node.named_children:
                ref = _reference(value_node, source, "sequence_item")
                if ref is not None:
                    refs.append(ref)

    def key(row: dict[str, Any]) -> tuple[int, int, str, str, str]:
        """Return the deterministic ordering key for a relation record.

        Parameters
        ----------
        row : dict[str, typing.Any]
            Call or callable-reference mapping to order.

        Returns
        -------
        tuple[int, int, str, str, str]
            Source location and relation identity ordering key.
        """
        return (
            row["lineno"],
            row["col_offset"],
            row["kind"],
            row.get("base", ""),
            row["target"],
        )

    return (
        sorted(calls, key=key),
        sorted(refs, key=lambda row: (*key(row), row["ref_kind"])),
    )


def _function_entry(
    function: Node, wrapper: Node | None, source: bytes, *, method: bool
) -> dict[str, Any]:
    """Convert one function definition into the legacy parsed-artifact mapping.

    Parameters
    ----------
    function : tree_sitter.Node
        Function-definition node to convert.
    wrapper : tree_sitter.Node | None
        Optional decorated-definition node owning ``function``.
    source : bytes
        UTF-8 source bytes owning the node.
    method : bool
        Whether the function belongs to a class body.

    Returns
    -------
    dict[str, typing.Any]
        Parsed callable mapping consumed by core normalization.
    """
    body = function.child_by_field_name("body")
    docstring, _ = _docstring(body, source)
    signature, parameters = _signature(function, source)
    local = _local_nodes(function)
    calls, refs = _calls_and_refs(function, source)
    return {
        "name": _text(function.child_by_field_name("name"), source),
        "lineno": _line(function),
        "end_lineno": function.end_point.row + 1,
        "signature": signature,
        "docstring": docstring,
        "has_docstring": int(docstring is not None),
        "is_method": int(method),
        "is_public": int(
            not _text(function.child_by_field_name("name"), source).startswith("_")
        ),
        "parameters": parameters,
        "returns_value": int(
            any(
                node.type == "return_statement" and node.named_children
                for node in local
            )
        ),
        "yields_value": int(
            any(node.type in {"yield", "yield_from"} for node in local)
        ),
        "raises": int(any(node.type == "raise_statement" for node in local)),
        "has_asserts": int(any(node.type == "assert_statement" for node in local)),
        "decorators": _decorators(wrapper, source),
        "calls": calls,
        "callable_refs": refs,
        "overloads": [],
    }


def _is_overload(entry: dict[str, Any]) -> bool:
    """Return whether one parsed callable mapping is a typing overload stub.

    Parameters
    ----------
    entry : dict[str, typing.Any]
        Callable mapping produced by ``_function_entry``.

    Returns
    -------
    bool
        ``True`` for ``@overload`` and ``@typing.overload`` callables.
    """
    return any(name in {"overload", "typing.overload"} for name in entry["decorators"])


def _overload(entry: dict[str, Any]) -> dict[str, Any]:
    """Select the persisted overload fields from one callable mapping.

    Parameters
    ----------
    entry : dict[str, typing.Any]
        Overload stub mapping.

    Returns
    -------
    dict[str, typing.Any]
        Overload metadata compatible with core normalization.
    """
    return {
        key: entry[key] for key in ("lineno", "end_lineno", "signature", "docstring")
    }


def _import_rows(node: Node, source: bytes) -> list[dict[str, Any]]:
    """Parse import statement text into normalized import mappings.

    Parameters
    ----------
    node : tree_sitter.Node
        Import or from-import statement node.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    list[dict[str, typing.Any]]
        Import rows in declaration order.
    """
    statement = _text(node, source).strip()
    line = _line(node)
    if statement.startswith("import "):
        return [
            {
                "name": part.strip().split(" as ")[0],
                "alias": (part.strip().split(" as ", 1)[1] if " as " in part else None),
                "lineno": line,
            }
            for part in statement[7:].split(",")
        ]
    match = re.match(r"from\s+([.\w]*)\s+import\s+(.+)$", statement, flags=re.S)
    if match is None:
        return []
    module, names = match.groups()
    return [
        {
            "name": f"{module}.{part.strip().split(' as ')[0]}"
            if module
            else part.strip().split(" as ")[0],
            "alias": (part.strip().split(" as ", 1)[1] if " as " in part else None),
            "lineno": line,
        }
        for part in names.strip("() ").split(",")
    ]


def _declaration(node: Node, source: bytes) -> dict[str, Any] | None:
    """Extract one top-level type alias or bounded literal constant.

    Parameters
    ----------
    node : tree_sitter.Node
        Top-level assignment or type-alias node.
    source : bytes
        UTF-8 source bytes owning the node.

    Returns
    -------
    dict[str, typing.Any] | None
        Declaration mapping when the node satisfies the bounded rules.
    """
    text = _text(node, source)
    name_node = node.child_by_field_name("left") or node.child_by_field_name("name")
    name = _text(name_node, source)
    signature = " ".join(text.split())
    if node.type == "type_alias_statement":
        return {
            "name": name,
            "kind": "type_alias",
            "lineno": _line(node),
            "signature": signature,
            "docstring": None,
        }
    annotation = node.child_by_field_name("type")
    annotation_text = _text(annotation, source)
    if annotation_text in {"TypeAlias", "typing.TypeAlias"}:
        return {
            "name": name,
            "kind": "type_alias",
            "lineno": _line(node),
            "signature": signature,
            "docstring": None,
        }
    value = node.child_by_field_name("right") or node.child_by_field_name("value")
    literal_types = {
        "integer",
        "float",
        "string",
        "true",
        "false",
        "none",
        "list",
        "tuple",
        "set",
        "dictionary",
    }
    if (
        name
        and not name.startswith("_")
        and any(char.isalpha() for char in name)
        and name.isupper()
        and value is not None
        and value.type in literal_types
    ):
        return {
            "name": name,
            "kind": "constant",
            "lineno": _line(node),
            "signature": signature,
            "docstring": None,
        }
    return None


def parse_python_artifacts(path: Path, root: Path, source: str) -> dict[str, Any]:
    """Parse Python source into persisted artifacts without host AST parsing.

    Parameters
    ----------
    path : pathlib.Path
        Logical source path associated with ``source``.
    root : pathlib.Path
        Repository root used for module-name derivation.
    source : str
        Decoded Python source text.

    Returns
    -------
    dict[str, typing.Any]
        Legacy parsed-artifact mapping consumed by core normalization.

    Raises
    ------
    SyntaxError
        If Tree-sitter reports invalid Python source or a legacy print statement.
    """
    source_bytes = source.encode("utf-8")
    tree = _new_parser().parse(source_bytes).root_node
    if tree.has_error or any(
        child.type == "print_statement" for child in tree.named_children
    ):
        msg = f"Python syntax errors prevent artifact extraction in {path}"
        raise SyntaxError(msg)
    module_doc, _ = _docstring(tree, source_bytes)
    result: dict[str, Any] = {
        "module": {
            "name": _module_name(path, root),
            "docstring": module_doc,
            "has_docstring": int(module_doc is not None),
        },
        "classes": [],
        "functions": [],
        "declarations": [],
        "imports": [],
    }
    pending_functions: dict[str, list[dict[str, Any]]] = {}
    for outer in tree.named_children:
        node = outer
        wrapper: Node | None = None
        if outer.type == "expression_statement" and outer.named_children:
            node = outer.named_children[0]
        if outer.type == "decorated_definition":
            wrapper = outer
            candidates = [
                child
                for child in outer.named_children
                if child.type
                in {
                    "function_definition",
                    "async_function_definition",
                    "class_definition",
                }
            ]
            if not candidates:
                continue
            node = candidates[-1]
        if node.type in {"import_statement", "import_from_statement"}:
            result["imports"].extend(_import_rows(node, source_bytes))
        elif node.type in {
            "assignment",
            "annotated_assignment",
            "type_alias_statement",
        }:
            declaration = _declaration(node, source_bytes)
            if declaration is not None:
                result["declarations"].append(declaration)
        elif node.type in {"function_definition", "async_function_definition"}:
            entry = _function_entry(node, wrapper, source_bytes, method=False)
            if _is_overload(entry):
                pending_functions.setdefault(entry["name"], []).append(_overload(entry))
            else:
                entry["overloads"] = pending_functions.pop(entry["name"], [])
                result["functions"].append(entry)
        elif node.type == "class_definition":
            body = node.child_by_field_name("body")
            docstring, _ = _docstring(body, source_bytes)
            class_entry: dict[str, Any] = {
                "name": _text(node.child_by_field_name("name"), source_bytes),
                "lineno": _line(node),
                "end_lineno": node.end_point.row + 1,
                "docstring": docstring,
                "has_docstring": int(docstring is not None),
                "methods": [],
            }
            pending_methods: dict[str, list[dict[str, Any]]] = {}
            for child_outer in body.named_children if body is not None else ():
                child = child_outer
                method_wrapper: Node | None = None
                if child_outer.type == "decorated_definition":
                    method_wrapper = child_outer
                    candidates = [
                        item
                        for item in child_outer.named_children
                        if item.type
                        in {"function_definition", "async_function_definition"}
                    ]
                    if not candidates:
                        continue
                    child = candidates[-1]
                if child.type not in {
                    "function_definition",
                    "async_function_definition",
                }:
                    continue
                entry = _function_entry(
                    child, method_wrapper, source_bytes, method=True
                )
                if _is_overload(entry):
                    pending_methods.setdefault(entry["name"], []).append(
                        _overload(entry)
                    )
                else:
                    entry["overloads"] = pending_methods.pop(entry["name"], [])
                    class_entry["methods"].append(entry)
            result["classes"].append(class_entry)
    return result


def module_docstring_location(source: str) -> tuple[int, int | None] | None:
    """Locate a syntactic module docstring without host AST parsing.

    Parameters
    ----------
    source : str
        Decoded Python source text.

    Returns
    -------
    tuple[int, int | None] | None
        One-based inclusive line range, or ``None`` without a module docstring.
    """
    source_bytes = source.encode("utf-8")
    _, node = _docstring(_new_parser().parse(source_bytes).root_node, source_bytes)
    if node is None:
        return None
    return (node.start_point.row + 1, node.end_point.row + 1)
