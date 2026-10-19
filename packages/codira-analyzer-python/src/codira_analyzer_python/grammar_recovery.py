"""Recover specific Python grammar gaps while preserving original source spans.

Parameters
----------
None

Returns
-------
None

Notes
-----
Parse views retain executable expression tokens. Provider tree edits restore
original byte and point coordinates; original bytes own extracted text. No host
AST, interpreter subprocess or source execution participates in recovery.
"""

from __future__ import annotations

import io
import keyword
import re
import tokenize
from bisect import bisect_right
from dataclasses import dataclass

from tree_sitter import Node, Parser


@dataclass(frozen=True)
class _Token:
    """Represent one significant lexical token with UTF-8 source offsets.

    Parameters
    ----------
    kind : int
        Standard tokenizer category.
    text : str
        Original token spelling.
    start, end : int
        Half-open byte range.

    Returns
    -------
    None
    """

    kind: int
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _Edit:
    """Describe one original-source replacement used only for parsing.

    Parameters
    ----------
    start, end : int
        Half-open original byte range, empty for an insertion.
    replacement : bytes
        Grammar-compatible parsing bytes.

    Returns
    -------
    None
    """

    start: int
    end: int
    replacement: bytes


def _tokens(source: bytes) -> tuple[_Token, ...] | None:
    """Tokenize UTF-8 source without consulting its encoding cookie again.

    Parameters
    ----------
    source : bytes
        Already decoded and re-encoded Python source.

    Returns
    -------
    tuple[_Token, ...] | None
        Significant tokens, or ``None`` for incomplete lexical input.
    """
    text = source.decode("utf-8")
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line.encode("utf-8")) + 1)
    ignored = {
        tokenize.ENCODING,
        tokenize.ENDMARKER,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.COMMENT,
    }
    result: list[_Token] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type in ignored:
                continue
            start_row, start_col = token.start
            end_row, end_col = token.end
            result.append(
                _Token(
                    token.type,
                    token.string,
                    offsets[start_row - 1]
                    + len(lines[start_row - 1][:start_col].encode("utf-8")),
                    offsets[end_row - 1]
                    + len(lines[end_row - 1][:end_col].encode("utf-8")),
                )
            )
    except (tokenize.TokenError, IndentationError, SyntaxError, SystemError):
        return None
    return tuple(result)


def _brackets(tokens: tuple[_Token, ...]) -> tuple[dict[int, int], list[int | None]]:
    """Collect matching delimiters and each token's enclosing opener.

    Parameters
    ----------
    tokens : tuple[_Token, ...]
        Significant lexical tokens.

    Returns
    -------
    tuple[dict[int, int], list[int | None]]
        Opener-to-closer indexes and immediate lexical parents.
    """
    pairs: dict[int, int] = {}
    parents: list[int | None] = []
    stack: list[int] = []
    for index, token in enumerate(tokens):
        parents.append(stack[-1] if stack else None)
        if token.kind != tokenize.OP:
            continue
        if token.text in {"(", "[", "{"}:
            stack.append(index)
        elif token.text in {")", "]", "}"} and stack:
            opening = stack.pop()
            if tokens[opening].text == {")": "(", "]": "[", "}": "{"}[token.text]:
                pairs[opening] = index
    return pairs, parents


def _headers(
    tokens: tuple[_Token, ...], pairs: dict[int, int]
) -> tuple[set[int], set[int]]:
    """Locate declaration type lists and function parameter lists.

    Parameters
    ----------
    tokens : tuple[_Token, ...]
        Significant lexical tokens.
    pairs : dict[int, int]
        Matching delimiter indexes.

    Returns
    -------
    tuple[set[int], set[int]]
        Type-list and parameter-list opening indexes.
    """
    types: set[int] = set()
    parameters: set[int] = set()
    for index, token in enumerate(tokens[:-2]):
        if token.kind != tokenize.NAME or token.text not in {"def", "class", "type"}:
            continue
        if tokens[index + 1].kind != tokenize.NAME:
            continue
        cursor = index + 2
        if tokens[cursor].text == "[" and cursor in pairs:
            types.add(cursor)
            cursor = pairs[cursor] + 1
        if token.text == "def" and cursor < len(tokens) and tokens[cursor].text == "(":
            parameters.add(cursor)
    return types, parameters


def _default_offsets(
    tokens: tuple[_Token, ...],
    pairs: dict[int, int],
    parents: list[int | None],
    types: set[int],
) -> tuple[int, ...]:
    """Select defaults only from structurally valid declaration type lists.

    Parameters
    ----------
    tokens : tuple[_Token, ...]
        Significant lexical tokens.
    pairs : dict[int, int]
        Matching delimiters.
    parents : list[int | None]
        Enclosing opener indexes.
    types : set[int]
        Declaration type-list opening indexes.

    Returns
    -------
    tuple[int, ...]
        Safe default separator offsets; malformed lists contribute none.
    """
    offsets: list[int] = []
    for opening in types:
        closing = pairs[opening]
        boundaries = [opening]
        boundaries.extend(
            i
            for i in range(opening + 1, closing)
            if parents[i] == opening and tokens[i].text == ","
        )
        boundaries.append(closing)
        selected: list[int] = []
        valid = True
        for begin, end in zip(boundaries, boundaries[1:]):
            if begin + 1 == end:
                valid = end == closing and begin != opening
                if not valid:
                    break
                continue
            first = begin + 1
            starred = tokens[first].text in {"*", "**"}
            name = first + int(starred)
            if (
                name >= end
                or tokens[name].kind != tokenize.NAME
                or keyword.iskeyword(tokens[name].text)
            ):
                valid = False
                break
            top = [i for i in range(name + 1, end) if parents[i] == opening]
            equals = [i for i in top if tokens[i].text == "="]
            colons = [i for i in top if tokens[i].text == ":"]
            if len(equals) > 1 or len(colons) > 1 or (starred and colons):
                valid = False
                break
            if top and tokens[top[0]].text not in {":", "="}:
                valid = False
                break
            if colons and (
                colons[0] + 1 == end or (equals and colons[0] >= equals[0] - 1)
            ):
                valid = False
                break
            if equals:
                equal = equals[0]
                if equal + 1 == end or (colons and colons[0] > equal):
                    valid = False
                    break
                selected.append(tokens[equal].start)
        if valid:
            offsets.extend(selected)
    return tuple(sorted(offsets))


def type_default_offsets(source: bytes) -> tuple[int, ...]:
    """Locate default separators in declaration type-parameter lists.

    Parameters
    ----------
    source : bytes
        Original UTF-8 source.

    Returns
    -------
    tuple[int, ...]
        Original byte offsets of top-level type-default equals signs.
    """
    tokens = _tokens(source)
    if tokens is None:
        return ()
    pairs, parents = _brackets(tokens)
    types, _ = _headers(tokens, pairs)
    return _default_offsets(tokens, pairs, parents, types)


def _annotation_edits(
    source: bytes,
    tokens: tuple[_Token, ...],
    pairs: dict[int, int],
    parents: list[int | None],
    parameters: set[int],
    parser: Parser,
) -> list[_Edit]:
    """Wrap independently valid slice annotations for the type grammar.

    Parameters
    ----------
    source : bytes
        Original UTF-8 source.
    tokens : tuple[_Token, ...]
        Significant lexical tokens.
    pairs : dict[int, int]
        Matching delimiter indexes.
    parents : list[int | None]
        Immediate lexical opener for each token.
    parameters : set[int]
        Function-parameter opening indexes.
    parser : tree_sitter.Parser
        Isolated provider parser for validating annotation expressions.

    Returns
    -------
    list[_Edit]
        Parenthesis insertions around valid expressions containing slices.
    """
    edits: list[_Edit] = []
    for opening in sorted(parameters):
        closing = pairs.get(opening)
        if closing is None:
            continue
        boundaries = [opening]
        boundaries.extend(
            index
            for index in range(opening + 1, closing)
            if parents[index] == opening and tokens[index].text == ","
        )
        boundaries.append(closing)
        for begin, end in zip(boundaries, boundaries[1:]):
            colon = next(
                (
                    index
                    for index in range(begin + 1, end)
                    if parents[index] == opening and tokens[index].text in {":", "="}
                ),
                None,
            )
            if colon is None or tokens[colon].text != ":":
                continue
            stop = next(
                (
                    index
                    for index in range(colon + 1, end)
                    if parents[index] == opening and tokens[index].text == "="
                ),
                end,
            )
            expression = tokens[colon + 1 : stop]
            if not expression or not any(t.text == "[" for t in expression):
                continue
            if not any(t.text == ":" for t in expression):
                continue
            start, finish = expression[0].start, expression[-1].end
            if parser.parse(source[start:finish]).root_node.has_error:
                continue
            edits.extend((_Edit(start, start, b"("), _Edit(finish, finish, b")")))
    return edits


def invalid_attribute_offsets(source: bytes) -> tuple[int, ...]:
    """Find bare line breaks after attribute dots outside delimiters.

    Parameters
    ----------
    source : bytes
        Original UTF-8 source.

    Returns
    -------
    tuple[int, ...]
        Dot byte offsets rejected by Python but accepted by the provider.
    """
    if re.search(rb"\.[ \t\r\f]*\n", source) is None:
        return ()
    tokens = _tokens(source)
    if tokens is None:
        return ()
    _, parents = _brackets(tokens)
    return tuple(
        token.start
        for index, token in enumerate(tokens[:-1])
        if token.text == "."
        and parents[index] is None
        and tokens[index + 1].kind == tokenize.NAME
        and b"\n" in source[token.end : tokens[index + 1].start]
        and not source[token.end : tokens[index + 1].start].strip(b" \t\r\n\f")
    )


def python_parse_root(source: bytes, parser: Parser) -> Node:
    """Parse known grammar gaps and restore original provider coordinates.

    Parameters
    ----------
    source : bytes
        Original UTF-8 source owning all extracted text.
    parser : tree_sitter.Parser
        Isolated parser using the bundled Python grammar.

    Returns
    -------
    tree_sitter.Node
        Clean original/recovered root, or original partial root on failure.

    Notes
    -----
    Only type-default separators, parenthesized starred subscript operands,
    independently valid slice annotations and whitespace after a dot inside
    delimiters are adapted. The final view must parse wholly without errors.
    Tree edits restore coordinates without reparsing the original grammar gaps.
    """
    original = parser.parse(source)
    if not original.root_node.has_error:
        return original.root_node
    tokens = _tokens(source)
    if tokens is None:
        return original.root_node
    pairs, parents = _brackets(tokens)
    types, parameters = _headers(tokens, pairs)
    edits = _annotation_edits(source, tokens, pairs, parents, parameters, parser)
    edits.extend(
        _Edit(offset, offset + 1, b":")
        for offset in _default_offsets(tokens, pairs, parents, types)
    )
    for index, token in enumerate(tokens):
        parent = parents[index]
        if index + 1 >= len(tokens):
            continue
        following = tokens[index + 1]
        if (
            token.text == "."
            and parent is not None
            and following.kind == tokenize.NAME
            and not keyword.iskeyword(following.text)
        ):
            gap = source[token.end : following.start]
            if b"\n" in gap and not gap.strip(b" \t\r\n\f"):
                edits.extend(
                    _Edit(token.end + offset, token.end + offset + 1, b" ")
                    for offset, byte in enumerate(gap)
                    if byte == 10
                )
        if (
            token.text != "*"
            or following.text != "("
            or parent is None
            or tokens[parent].text != "["
            or parent in types
            or parent == 0
        ):
            continue
        before = tokens[parent - 1]
        subscription = (
            before.kind == tokenize.NAME and not keyword.iskeyword(before.text)
        ) or before.text in {")", "]"}
        item_start = index == parent + 1 or (
            tokens[index - 1].text == "," and parents[index - 1] == parent
        )
        if subscription and item_start:
            edits.append(_Edit(token.start, token.end, b" "))
    if not edits:
        return original.root_node
    view = bytearray()
    reverse: list[tuple[int, int, bytes]] = []
    cursor = 0
    for edit in sorted(edits, key=lambda item: (item.start, item.end)):
        if edit.start < cursor:
            return original.root_node
        view.extend(source[cursor : edit.start])
        start = len(view)
        view.extend(edit.replacement)
        reverse.append((start, len(view), source[edit.start : edit.end]))
        cursor = edit.end
    view.extend(source[cursor:])
    tree = parser.parse(bytes(view))
    if tree.root_node.has_error:
        return original.root_node
    line_starts = [0] + [index + 1 for index, byte in enumerate(view) if byte == 10]
    for start, end, restored in reversed(reverse):
        row = bisect_right(line_starts, start) - 1
        old_row = bisect_right(line_starts, end) - 1
        point = (row, start - line_starts[row])
        rows = restored.count(b"\n")
        new_point = (
            (row + rows, len(restored.rsplit(b"\n", 1)[-1]))
            if rows
            else (row, point[1] + len(restored))
        )
        tree.edit(
            start_byte=start,
            old_end_byte=end,
            new_end_byte=start + len(restored),
            start_point=point,
            old_end_point=(old_row, end - line_starts[old_row]),
            new_end_point=new_point,
        )
    return tree.root_node
