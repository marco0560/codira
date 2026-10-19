"""Coordinate-preserving Bash views for word and redirect grammar omissions.

Parameters
----------
None

Returns
-------
None
    Defines syntax-only views; artifact text always comes from original bytes.
"""

from __future__ import annotations

import re

from tree_sitter import Node, Parser

_PARAMETER = re.compile(rb"(?:[A-Za-z_][A-Za-z_0-9]*|[0-9@*?!$-])(?:\[[^\n]*?\])?")
_LITERALS = frozenset({"raw_string", "ansi_c_string", "comment", "heredoc_body"})


def _nodes(root: Node) -> list[Node]:
    """Collect syntax nodes without sharing mutable parser state.

    Parameters
    ----------
    root : tree_sitter.Node
        Original provider root.

    Returns
    -------
    list[tree_sitter.Node]
        Nodes in source order, including punctuation and recovery observations.
    """
    result: list[Node] = []
    pending = [root]
    while pending:
        node = pending.pop()
        result.append(node)
        pending.extend(reversed(node.children))
    return result


def _contains(position: int, ranges: list[tuple[int, int]]) -> bool:
    """Return whether a byte belongs to a protected source range.

    Parameters
    ----------
    position : int
        Original byte offset.
    ranges : list[tuple[int, int]]
        Half-open protected ranges.

    Returns
    -------
    bool
        Whether the byte belongs to a range.
    """
    return any(start <= position < end for start, end in ranges)


def _parameters(
    source: bytes, protected: list[tuple[int, int]], substitutions: dict[int, int]
) -> dict[int, int]:
    """Find balanced parameter expansions while preserving embedded shell code.

    Parameters
    ----------
    source : bytes
        Original source bytes.
    protected : list[tuple[int, int]]
        Comments and non-expanding literals.
    substitutions : dict[int, int]
        Provider-recognized command/arithmetic substitution ranges.

    Returns
    -------
    dict[int, int]
        Expansion starts mapped to exclusive ends.
    """
    result: dict[int, int] = {}

    def closing(start: int) -> int | None:
        """Locate one closing brace without entering nested substitutions.

        Parameters
        ----------
        start : int
            Dollar byte of a parameter expansion.

        Returns
        -------
        int | None
            Exclusive end, or no end for an incomplete expansion.
        """
        index = start + 2
        quote = 0
        while index < len(source):
            byte = source[index]
            if byte == ord("\\"):
                index += 2
                continue
            if index in substitutions:
                index = substitutions[index]
                continue
            if source[index : index + 2] == b"${":
                end = closing(index)
                if end is None:
                    return None
                index = end
                continue
            if byte in (ord("'"), ord('"')):
                if not quote:
                    quote = byte
                elif quote == byte:
                    quote = 0
            if byte == ord("}") and not quote:
                result[start] = index + 1
                return index + 1
            index += 1
        return None

    for match in re.finditer(rb"\$\{", source):
        start = match.start()
        if start in result or _contains(start, protected):
            continue
        before = start - 1
        while before >= 0 and source[before] == ord("\\"):
            before -= 1
        if (start - before - 1) % 2:
            continue
        closing(start)
    return result


def bash_parse_root(parser: Parser, source: bytes) -> Node:
    """Recover complete Bash views without changing artifact source coordinates.

    Parameters
    ----------
    parser : tree_sitter.Parser
        Isolated Bash parser.
    source : bytes
        Original source used for every artifact and signature.

    Returns
    -------
    tree_sitter.Node
        Original clean/partial root, or an entirely clean recovered view.

    Notes
    -----
    Views normalize literal word punctuation and redirect/comparison shapes
    omitted by the bundled grammar. They do not evaluate words, conditions or
    arithmetic, execute shell code, or resolve command names. Nested command
    substitutions remain syntax. Residual errors discard the entire view.
    """
    original = parser.parse(source).root_node
    if not original.has_error:
        return original
    nodes = _nodes(original)
    protected = [(n.start_byte, n.end_byte) for n in nodes if n.type in _LITERALS]
    word_literals = protected + [
        (n.start_byte, n.end_byte) for n in nodes if n.type == "string_content"
    ]
    substitutions = {
        n.start_byte: n.end_byte
        for n in nodes
        if n.type
        in {"command_substitution", "process_substitution", "arithmetic_expansion"}
    }
    expansions = _parameters(source, protected, substitutions)
    projected = bytearray(source)
    for start, end in expansions.items():
        name = _PARAMETER.match(source, start + 2)
        if name is None:
            continue
        operator = name.end()
        token = source[operator : operator + 2]
        if token in {b":-", b":+", b":?", b":=", b"##", b"%%"}:
            word = operator + 2
        elif source[operator : operator + 1] in {
            b"-",
            b"+",
            b"?",
            b"=",
            b"#",
            b"%",
            b":",
        }:
            word = operator + 1
        else:
            continue
        pattern = source[operator : operator + 1] in {b"#", b"%"}
        slice_word = source[operator : operator + 1] == b":" and token not in {
            b":-",
            b":+",
            b":?",
            b":=",
        }
        index = word
        while index < end - 1:
            if index in substitutions:
                index = substitutions[index]
                continue
            if index in expansions:
                index = expansions[index]
                continue
            if not _contains(index, protected):
                byte = source[index]
                if byte in b";()" or (pattern and byte in b"[]"):
                    projected[index] = ord("_")
                elif slice_word and byte == ord("$"):
                    projected[index] = ord("_")
            index += 1
    for node in nodes:
        if node.type == "subscript" and node.has_error:
            for index in range(node.start_byte, node.end_byte):
                if (
                    source[index] in b":$"
                    and not _contains(index, word_literals)
                    and not _contains(index, list(substitutions.items()))
                ):
                    projected[index] = ord("_")
            for start, end in expansions.items():
                if node.start_byte <= start and end <= node.end_byte:
                    projected[start + 1] = ord("_")
                    projected[end - 1] = ord("_")
        if (
            node.is_error
            and node.parent is not None
            and node.parent.type == "case_statement"
        ):
            text = source[node.start_byte : node.end_byte]
            if (
                text.startswith(b'*"')
                and b"\n" not in text
                and re.fullmatch(rb'(?:\*|"[^"$`\\]*")+', text)
            ):
                projected[node.start_byte : node.end_byte] = b"_" * len(text)
        if node.type == "=":
            ancestor = node.parent
            while ancestor is not None:
                if ancestor.type == "test_command":
                    projected[node.start_byte] = ord("<")
                    break
                if ancestor.type in {
                    "command_substitution",
                    "command",
                    "variable_assignment",
                }:
                    break
                ancestor = ancestor.parent
        if node.type == "variable_assignment" and node.parent is not None:
            parent = node.parent
            following = node.next_named_sibling
            while following is not None and following.type == "comment":
                following = following.next_named_sibling
            if (
                parent.has_error
                and following is not None
                and following.type == "file_redirect"
            ):
                equal = source.find(b"=", node.start_byte, node.end_byte)
                if equal >= 0 and re.fullmatch(
                    rb"[A-Za-z_][A-Za-z_0-9]*", source[node.start_byte : equal]
                ):
                    projected[equal] = ord(" ")
        if node.is_error and source[node.start_byte : node.start_byte + 1] == b"@":
            match = re.match(rb"[A-Za-z_0-9@./-]+", source[node.start_byte :])
            if match is not None:
                for index in range(node.start_byte, node.start_byte + match.end()):
                    if source[index] == ord("@"):
                        projected[index] = ord("_")
    for match in re.finditer(rb"<<<", source):
        if not _contains(match.start(), word_literals):
            projected[match.start() + 1 : match.end()] = b"  "
    for match in re.finditer(rb"\{(?=\S)", source):
        start = match.start()
        if _contains(start, word_literals) or _contains(
            start, list(expansions.items())
        ):
            continue
        index = start
        depth = 0
        while index < len(source) and source[index] not in b" \t\r\n'\"":
            byte = source[index]
            depth += int(byte == ord("{")) - int(byte == ord("}"))
            if depth == 0:
                if b"," in source[start : index + 1]:
                    for offset in range(start, index + 1):
                        if source[offset] in b"{}":
                            projected[offset] = ord("_")
                break
            index += 1
    if projected == source:
        return original
    recovered = parser.parse(bytes(projected)).root_node
    return original if recovered.has_error else recovered
