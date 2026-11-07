"""Resolve namespace declaration names in an explicit identifier-macro profile.

Parameters
----------
None

Returns
-------
None
    Provides bounded namespace-name projection without conditional evaluation.
"""

from __future__ import annotations

import re

from .cpp_preprocessing import (
    _ANNOTATION_NODES,
    _IDENTIFIER,
    _annotation_definitions,
    _AnnotationDefinitions,
    _collect_annotation_definitions,
    _nodes,
    _parse_cpp_source,
)
from .cpp_projection import SyntaxNode, _ProjectedNode, _source_projection
from .cpp_syntax import _LANGUAGE, _new_parser


def _namespace_bindings_from_config(value: object) -> tuple[tuple[bytes, bytes], ...]:
    """Validate explicit identifier replacements for namespace declarations.

    Parameters
    ----------
    value : object
        Configuration object mapping macro names to identifier strings.

    Returns
    -------
    tuple[tuple[bytes, bytes], ...]
        Sorted ASCII macro names and namespace identifiers.

    Raises
    ------
    ValueError
        If names or replacements are not single non-keyword C++ identifiers.
    """
    if not isinstance(value, dict):
        raise ValueError("namespace_macro_definitions must be an identifier mapping")
    parser = _new_parser()
    result: list[tuple[bytes, bytes]] = []
    for name, replacement in value.items():
        if not isinstance(name, str) or not isinstance(replacement, str):
            raise ValueError(
                "namespace_macro_definitions must be an identifier mapping"
            )
        pair: list[bytes] = []
        for token in (name, replacement):
            if (
                re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", token) is None
                or _LANGUAGE.id_for_node_kind(token, False) is not None
            ):
                raise ValueError("namespace_macro_definitions requires identifiers")
            raw = token.encode("ascii")
            tree = parser.parse(b"namespace " + raw + b" {}").root_node
            if tree.has_error or tree.named_children[0].type != "namespace_definition":
                raise ValueError("namespace_macro_definitions rejects C++ keywords")
            pair.append(raw)
        result.append((pair[0], pair[1]))
    return tuple(sorted(result))


def _parse_with_namespace_bindings(
    source: bytes,
    *,
    included_sources: tuple[tuple[bytes, int], ...] = (),
    bindings: tuple[tuple[bytes, bytes], ...] = (),
) -> SyntaxNode:
    """Map proven namespace declaration aliases under explicit external bindings.

    Parameters
    ----------
    source : bytes
        Original source, retained for artifact snippets and positions.
    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured contained headers and their reaching source boundaries.
    bindings : tuple[tuple[bytes, bytes], ...], optional
        Explicit compiler-style identifier bindings, limited to namespace names.

    Returns
    -------
    SyntaxNode
        Existing tree, or a projected tree retaining original coordinates.

    Raises
    ------
    ValueError
        If captured directives contradict the explicit profile, or a reaching
        namespace alias connected to it has no unique supported replacement.

    Notes
    -----
    No branch selection or general expression substitution occurs. Source
    overrides of configured names or replacements are held. Scope wrappers and
    explicit namespace names share a single original-coordinate projection.
    """
    root = _parse_cpp_source(source, included_sources=included_sources)
    if not bindings:
        return root
    parser = _new_parser()
    state = _AnnotationDefinitions()
    for content, boundary in ((source, None), *included_sources):
        _collect_annotation_definitions(
            content, parser.parse(content).root_node, boundary, state
        )
    blocked = set(state.replacements) | state.unsafe
    if b"namespace" in blocked or b"inline" in blocked:
        if root.has_error:
            return root
        raise ValueError(
            "namespace_macro_definitions conflicts with namespace keywords"
        )
    if any(
        name in state.unsafe
        or replacement in blocked
        or any(
            value.strip() != replacement for value in state.replacements.get(name, [])
        )
        for name, replacement in bindings
    ):
        if root.has_error:
            return root
        raise ValueError("namespace_macro_definitions conflicts with captured source")
    related = {name for name, _ in bindings}
    changed = True
    while changed:
        changed = False
        for name, alternatives in state.replacements.items():
            if name not in related and any(
                related.intersection(_IDENTIFIER.findall(value))
                for value in alternatives
            ):
                related.add(name)
                changed = True
    annotations = _annotation_definitions(source, root, parser, included_sources)
    resolved: dict[bytes, tuple[bytes, int]] = {
        name: (replacement, 0) for name, replacement in bindings
    }
    changed = True
    while changed:
        changed = False
        for name, alternatives in state.replacements.items():
            if name not in related or name in resolved or name in state.unsafe:
                continue
            names: set[bytes] = set()
            boundary = state.first_offsets[name]
            for value in alternatives:
                for token in _IDENTIFIER.findall(value):
                    if token in annotations:
                        boundary = max(boundary, annotations[token])
                value = _IDENTIFIER.sub(
                    lambda match: (
                        b" " * len(match[0]) if match[0] in annotations else match[0]
                    ),
                    value,
                )
                probe = b"namespace " + value + b" { int __codira_probe; }"
                tree = parser.parse(probe).root_node
                if tree.has_error or len(tree.named_children) != 1:
                    break
                declaration = tree.named_children[0]
                identifier: SyntaxNode | None = declaration.child_by_field_name("name")
                if (
                    declaration.type != "namespace_definition"
                    or identifier is None
                    or identifier.type != "namespace_identifier"
                    or any(
                        child.type
                        not in _ANNOTATION_NODES
                        | {"namespace_identifier", "declaration_list"}
                        for child in declaration.named_children
                    )
                ):
                    break
                target = probe[identifier.start_byte : identifier.end_byte]
                if target not in resolved:
                    break
                names.add(resolved[target][0])
                boundary = max(boundary, resolved[target][1])
            else:
                if len(names) == 1:
                    resolved[name] = (names.pop(), boundary)
                    changed = True
    if root.has_error or isinstance(root, _ProjectedNode):
        for node in _nodes(parser.parse(source).root_node):
            if node.type != "namespace_definition":
                continue
            identifier = node.child_by_field_name("name")
            if identifier is None:
                continue
            token = source[identifier.start_byte : identifier.end_byte]
            if (
                token in related
                and token not in resolved
                and identifier.start_byte >= state.first_offsets.get(token, 0)
            ):
                if root.has_error:
                    return root
                raise ValueError(
                    "namespace_macro_definitions cannot resolve namespace alias "
                    + token.decode("ascii")
                )
        recovered = _parse_cpp_source(
            source,
            included_sources=included_sources,
            namespace_bindings=tuple(
                (name, value, boundary) for name, (value, boundary) in resolved.items()
            ),
        )
        if not recovered.has_error:
            return recovered
        if root.has_error:
            return root
    replacements: list[tuple[int, int, bytes]] = []
    for node in _nodes(root):
        if node.type != "namespace_definition":
            continue
        identifier = node.child_by_field_name("name")
        if identifier is None or identifier.type != "namespace_identifier":
            continue
        token = source[identifier.start_byte : identifier.end_byte]
        if (
            token in related
            and token not in resolved
            and identifier.start_byte >= state.first_offsets.get(token, 0)
        ):
            raise ValueError(
                "namespace_macro_definitions cannot resolve namespace alias "
                + token.decode("ascii")
            )
        if token in resolved and identifier.start_byte >= resolved[token][1]:
            replacements.append(
                (identifier.start_byte, identifier.end_byte, resolved[token][0])
            )
    if not replacements:
        return root
    if isinstance(root, _ProjectedNode):
        return parser.parse(source).root_node
    working = root.text
    if working is None:
        return root
    projection = _source_projection(working, sorted(replacements))
    recovered = parser.parse(projection.expanded).root_node
    return root if recovered.has_error else projection.tree(recovered)
