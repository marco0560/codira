"""Recover parameter identities from compatible captured macro alternatives.

Parameters
----------
None

Returns
-------
None
    Supplies metadata only; source signatures and parse coordinates stay intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tree_sitter import Node

from .c_parser import _new_parser
from .c_preprocessing import _c_language_source, _nodes, _pragma_source

_IDENTIFIER = rb"[A-Za-z_][A-Za-z_0-9]*"


@dataclass(frozen=True)
class ParameterMacro:
    """Hold one captured replacement and its original availability boundary.

    Parameters
    ----------
    argument : bytes | None
        Single formal argument, or None for an object macro.
    replacement : bytes
        Unexpanded source replacement with line splices joined.
    available_after : int
        Original source offset after which this definition is available.

    Returns
    -------
    None
        Immutable parameter-metadata input.
    """

    argument: bytes | None
    replacement: bytes
    available_after: int


def parameter_macros(
    source: bytes, included_sources: tuple[tuple[bytes, int], ...]
) -> dict[bytes, tuple[ParameterMacro, ...]]:
    """Collect compatible-shape candidates while rejecting undefinitions.

    Parameters
    ----------
    source : bytes
        Original translation-unit bytes.
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers with original source availability boundaries.

    Returns
    -------
    dict[bytes, tuple[ParameterMacro, ...]]
        All observed names; an empty tuple marks an unsafe candidate.
    """
    parser = _new_parser()
    definitions: dict[bytes, list[ParameterMacro]] = {}
    unsafe: set[bytes] = set()
    for content, boundary in ((source, -1), *included_sources):
        tree = parser.parse(content).root_node
        content = _c_language_source(content, tree)
        tree = parser.parse(content).root_node
        for node in _nodes(tree):
            if node.type == "preproc_call":
                match = re.match(
                    rb"#\s*undef\s+(" + _IDENTIFIER + rb")",
                    content[node.start_byte : node.end_byte],
                )
                if match:
                    unsafe.add(match[1])
            if node.type not in {"preproc_def", "preproc_function_def"}:
                continue
            name = node.child_by_field_name("name")
            if name is None:
                continue
            token = content[name.start_byte : name.end_byte]
            definitions.setdefault(token, [])
            argument = None
            if node.type == "preproc_function_def":
                parameters = node.child_by_field_name("parameters")
                text = (
                    content[parameters.start_byte : parameters.end_byte]
                    if parameters
                    else b""
                )
                match = re.fullmatch(rb"\(\s*(" + _IDENTIFIER + rb")\s*\)", text)
                if match is None:
                    unsafe.add(token)
                    continue
                argument = match[1]
            value = node.child_by_field_name("value")
            replacement = content[value.start_byte : value.end_byte] if value else b""
            definitions[token].append(
                ParameterMacro(
                    argument,
                    re.sub(rb"\\\r?\n", b" ", replacement),
                    node.end_byte if boundary < 0 else boundary,
                )
            )
    for unsafe_name in unsafe:
        definitions.setdefault(unsafe_name, [])
    return {
        name: () if name in unsafe else tuple(values)
        for name, values in definitions.items()
    }


def _plain_identifier(replacement: bytes) -> bytes | None:
    """Require one identifier after independently parsed compiler annotations.

    Parameters
    ----------
    replacement : bytes
        Substituted identifier wrapper, optionally carrying compiler attributes.

    Returns
    -------
    bytes | None
        Proven plain identifier, or None for a larger declaration or expression.
    """
    parser = _new_parser()
    source = b"void __codira_probe(int " + replacement + b");"
    source = _pragma_source(source, parser.parse(source).root_node)
    root = parser.parse(source).root_node
    if root.has_error:
        return None
    projected = bytearray(source)
    for node in _nodes(root):
        if node.type in {"attribute_specifier", "attribute_declaration"}:
            projected[node.start_byte : node.end_byte] = b" " * (
                node.end_byte - node.start_byte
            )
    value = bytes(projected)[len(b"void __codira_probe(int ") : -2].strip()
    return value if re.fullmatch(_IDENTIFIER, value) else None


def macro_parameter_name(
    parameter: Node,
    source: bytes,
    definitions: dict[bytes, tuple[ParameterMacro, ...]],
) -> str | None:
    """Resolve a plain object parameter or a single-identifier wrapper.

    Parameters
    ----------
    parameter : tree_sitter.Node
        One original-coordinate parameter declaration.
    source : bytes
        Unmodified signature source.
    definitions : dict[bytes, tuple[ParameterMacro, ...]]
        Captured alternatives and unsafe names from every input.

    Returns
    -------
    str | None
        Agreed name from every alternative, or None when proof is incomplete.
    """
    text = source[parameter.start_byte : parameter.end_byte].strip()
    declarator = parameter.child_by_field_name("declarator")
    while declarator is not None and declarator.type == "pointer_declarator":
        declarator = declarator.child_by_field_name("declarator")
    argument = None
    if declarator is None:
        token = text
    elif declarator.type == "function_declarator":
        invocation = source[declarator.start_byte : declarator.end_byte]
        match = re.fullmatch(
            rb"(" + _IDENTIFIER + rb")\s*\(\s*(" + _IDENTIFIER + rb")\s*\)", invocation
        )
        if match is None or match[2] in definitions:
            return None
        token, argument = match[1], match[2]
    else:
        return None
    alternatives = definitions.get(token, ())
    if (
        not alternatives
        or min(value.available_after for value in alternatives) > parameter.start_byte
    ):
        return None
    names: set[bytes] = set()
    for value in alternatives:
        if (value.argument is None) != (argument is None):
            return None
        replacement = value.replacement.strip()
        if value.argument is None:
            match = re.fullmatch(
                rb"(" + _IDENTIFIER + rb")\s+(" + _IDENTIFIER + rb")", replacement
            )
            if match is None or match[1] in definitions:
                return None
            name = match[2]
            probe = b"void __codira_probe(" + replacement + b");"
            parsed = _new_parser().parse(probe).root_node
            if parsed.has_error:
                return None
            parameters = [
                n for n in _nodes(parsed) if n.type == "parameter_declaration"
            ]
            if len(parameters) != 1:
                return None
            declared = parameters[0].child_by_field_name("declarator")
            if (
                declared is None
                or declared.type != "identifier"
                or probe[declared.start_byte : declared.end_byte] != name
            ):
                return None
        else:
            assert argument is not None
            if any(
                token in definitions
                for token in (b"__attribute__", b"__declspec", b"__pragma", b"_Pragma")
            ):
                return None
            replacement = re.sub(
                rb"\b" + re.escape(value.argument) + rb"\b", argument, replacement
            )
            replacement = re.sub(
                rb"(" + _IDENTIFIER + rb")\s*##\s*(" + _IDENTIFIER + rb")",
                rb"\1\2",
                replacement,
            )
            name = _plain_identifier(replacement)
            if name is None:
                return None
        if name in definitions:
            return None
        names.add(name)
    return next(iter(names)).decode("ascii") if len(names) == 1 else None
