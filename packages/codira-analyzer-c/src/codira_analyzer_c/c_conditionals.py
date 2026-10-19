"""Recover complete conditional statements and written C signature alternatives.

Parameters
----------
None

Returns
-------
None
    Coordinate-preserving views; no condition evaluation or macro expansion.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from tree_sitter import Node, Parser

from .c_preprocessing import _c_language_source, _nodes, _parse_c_source

_DIRECTIVE = re.compile(
    rb"(?m)^[ \t]*#[ \t]*(ifdef|ifndef|if|elif|else|endif)\b([^\r\n]*)"
)
_OPAQUE = frozenset(
    {
        "comment",
        "string_literal",
        "char_literal",
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
        "preproc_include",
    }
)


@dataclass(frozen=True)
class CParseView:
    """Keep original signature bytes beside their projected syntax tree.

    Parameters
    ----------
    source : bytes
        Same-coordinate source with inactive headers and selected directives blanked.
    root : tree_sitter.Node
        Parsed root; annotation identifiers may additionally be blank in the tree.

    Returns
    -------
    None
        Equal-coordinate source and grammar view; callers retain header context.
    """

    source: bytes
    root: Node


@dataclass
class _Conditional:
    """Track one balanced lexical conditional and its written alternatives.

    Parameters
    ----------
    start : int
        Opening directive byte offset.
    branch_start : int
        Current branch content start.
    directives : list[tuple[int, int]]
        Directive spans including opening and closing lines.
    branches : list[tuple[int, int]], optional
        Completed branch content spans.
    end : int, optional
        End of the closing directive.
    has_else : bool, optional
        Whether an explicit final alternative exists.

    Returns
    -------
    None
        Mutable state confined to one conditional scan.
    """

    start: int
    branch_start: int
    directives: list[tuple[int, int]]
    branches: list[tuple[int, int]] = field(default_factory=list)
    end: int = 0
    has_else: bool = False


def _valid_directive(kind: bytes, suffix: bytes, parser: Parser) -> bool:
    """Require grammar-valid directives before removing their syntax wrappers.

    Parameters
    ----------
    kind : bytes
        Conditional directive keyword.
    suffix : bytes
        Written condition or trailing comment.
    parser : tree_sitter.Parser
        C grammar used for independent small directive probes.

    Returns
    -------
    bool
        Whether a complete isolated conditional parses without errors.
    """
    if kind in {b"if", b"ifdef", b"ifndef", b"elif"}:
        opener = b"if" if kind == b"elif" else kind
        probe = b"#" + opener + suffix + b"\nint __codira_probe;\n#endif\n"
    elif kind == b"else":
        probe = b"#if 1\n#else" + suffix + b"\n#endif\n"
    else:
        probe = b"#if 1\n#endif" + suffix + b"\n"
    return not parser.parse(probe).root_node.has_error


def _conditionals(
    source: bytes, root: Node, parser: Parser
) -> list[_Conditional] | None:
    """Scan balanced directives while excluding literals, comments and macros.

    Parameters
    ----------
    source : bytes
        Source buffer with original coordinates.
    root : tree_sitter.Node
        Tree supplying opaque spans.
    parser : tree_sitter.Parser
        C grammar for directive validation.

    Returns
    -------
    list[_Conditional] | None
        Completed groups, or None for malformed or unsupported directives.
    """
    opaque = [(n.start_byte, n.end_byte) for n in _nodes(root) if n.type in _OPAQUE]
    stack: list[_Conditional] = []
    groups: list[_Conditional] = []
    for match in _DIRECTIVE.finditer(source):
        offset = source.index(b"#", match.start(), match.end())
        if any(start < offset < end for start, end in opaque):
            continue
        kind = match[1]
        if not _valid_directive(kind, match[2], parser):
            return None
        span = (match.start(), match.end())
        if kind in {b"if", b"ifdef", b"ifndef"}:
            stack.append(_Conditional(match.start(), match.end(), [span]))
        elif kind in {b"elif", b"else"}:
            if not stack or stack[-1].has_else:
                return None
            group = stack[-1]
            group.branches.append((group.branch_start, match.start()))
            group.branch_start = match.end()
            group.directives.append(span)
            group.has_else = kind == b"else"
        else:
            if not stack:
                return None
            group = stack.pop()
            group.branches.append((group.branch_start, match.start()))
            group.directives.append(span)
            group.end = match.end()
            groups.append(group)
    return None if stack else groups


def _blank(source: bytes, spans: list[tuple[int, int]]) -> bytes:
    """Blank selected spans while retaining byte positions and line endings.

    Parameters
    ----------
    source : bytes
        Original or partially projected source.
    spans : list[tuple[int, int]]
        Half-open byte ranges to blank.

    Returns
    -------
    bytes
        Same-length source retaining every newline and carriage return.
    """
    projected = bytearray(source)
    for start, end in spans:
        projected[start:end] = bytes(
            c if c in (10, 13) else 32 for c in source[start:end]
        )
    return bytes(projected)


def _slice_inputs(
    included_sources: tuple[tuple[bytes, int], ...],
    start: int,
    end: int,
    prefix: int = 0,
) -> tuple[tuple[bytes, int], ...]:
    """Rebase captured definition availability for an isolated source probe.

    Parameters
    ----------
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers with original-source include boundaries.
    start : int
        Original start of the probed source fragment.
    end : int
        Original end of that fragment.
    prefix : int, optional
        Synthetic probe prefix byte count.

    Returns
    -------
    tuple[tuple[bytes, int], ...]
        Only headers available by the fragment end, at adjusted boundaries.
    """
    return tuple(
        (content, 0 if boundary <= start else prefix + boundary - start)
        for content, boundary in included_sources
        if boundary <= end
    )


def _complete_header(
    fragment: bytes,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> bool:
    """Recognize a complete function header needing only its shared body.

    Parameters
    ----------
    fragment : bytes
        One written conditional alternative.
    parser : tree_sitter.Parser
        C grammar parser.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and original or probe-adjusted availability.

    Returns
    -------
    bool
        True for exactly one function definition with the appended probe body.
    """
    root = _parse_c_source(fragment + b"\n{}", parser, included_sources)
    declarations = [node for node in root.named_children if node.type != "comment"]
    if (
        root.has_error
        or len(declarations) != 1
        or declarations[0].type != "function_definition"
    ):
        return False
    body = declarations[0].child_by_field_name("body")
    return body is not None and body.start_byte >= len(fragment)


def _header_groups(
    source: bytes,
    root: Node,
    groups: list[_Conditional],
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> list[_Conditional]:
    """Find disjoint complete header choices outside function and record bodies.

    Parameters
    ----------
    source : bytes
        C-only source buffer.
    root : tree_sitter.Node
        Root identifying existing function/record body boundaries.
    groups : list[_Conditional]
        Balanced lexical conditional groups.
    parser : tree_sitter.Parser
        C parser for isolated header probes.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and original or probe-adjusted availability.

    Returns
    -------
    list[_Conditional]
        Independent header groups with explicit final alternatives and shared bodies.
    """
    bodies = [
        body
        for node in _nodes(root)
        if node.type
        in {
            "function_definition",
            "struct_specifier",
            "union_specifier",
            "enum_specifier",
        }
        and (body := node.child_by_field_name("body")) is not None
    ]
    headers: list[_Conditional] = []
    for group in sorted(groups, key=lambda item: item.start):
        if not group.has_else or any(
            body.start_byte <= group.start < body.end_byte for body in bodies
        ):
            continue
        tail = re.sub(
            rb"\A(?:\s|/\*.*?\*/|//[^\n]*(?:\n|$))*",
            b"",
            source[group.end :],
            count=1,
            flags=re.DOTALL,
        )
        if not tail.startswith(b"{"):
            continue
        if all(
            _complete_header(
                source[start:end], parser, _slice_inputs(included_sources, start, end)
            )
            for start, end in group.branches
        ):
            if headers and group.start < headers[-1].end:
                return []
            headers.append(group)
    return headers


def _statement_projection(
    source: bytes, parser: Parser, included_sources: tuple[tuple[bytes, int], ...] = ()
) -> bytes:
    """Remove wrappers only around complete statement alternatives in bodies.

    Parameters
    ----------
    source : bytes
        Source with selected complete headers.
    parser : tree_sitter.Parser
        C parser used for body detection and statement probes.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and original or probe-adjusted availability.

    Returns
    -------
    bytes
        All written statements retained, with eligible directive lines blanked.
    """
    root = _parse_c_source(source, parser, included_sources)
    groups = _conditionals(source, root, parser)
    if groups is None:
        return source
    bodies = [
        body
        for node in _nodes(root)
        if node.type == "function_definition"
        and (body := node.child_by_field_name("body")) is not None
    ]
    projected = source
    for group in sorted(groups, key=lambda item: item.end - item.start):
        if not any(
            body.start_byte <= group.start and group.end <= body.end_byte
            for body in bodies
        ):
            continue
        complete = True
        for start, end in group.branches:
            branch = projected[start:end]
            probes = [
                b"void __codira_probe(void) {\n" + branch + b"\n}",
                b"void __codira_probe(void) { if (0) {}\n" + branch + b"\n}",
            ]
            if all(
                _parse_c_source(
                    probe,
                    parser,
                    _slice_inputs(
                        included_sources, start, end, len(probe) - len(branch) - 2
                    ),
                ).has_error
                for probe in probes
            ):
                complete = False
                break
        if complete:
            projected = _blank(projected, group.directives)
    return projected


def c_parse_views(
    source: bytes,
    parser: Parser,
    *,
    base: Node | None = None,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> Iterator[CParseView]:
    """Yield views covering every independent written signature alternative.

    Parameters
    ----------
    source : bytes
        Original C source bytes.
    parser : tree_sitter.Parser
        Package-local C parser.
    base : tree_sitter.Node | None, optional
        Already parsed base recovery for exactly these source bytes.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and original or probe-adjusted availability.

    Returns
    -------
    collections.abc.Iterator[CParseView]
        Unchanged clean/base view, or linear covering views of complete headers.
        Callers must retain partial status if any generated view contains errors.
    """
    if base is None:
        base = _parse_c_source(source, parser, included_sources)
    if not base.has_error:
        return iter((CParseView(source, base),))
    working = _c_language_source(source, base)
    root = parser.parse(working).root_node
    groups = _conditionals(working, root, parser)
    if groups is None:
        return iter((CParseView(source, base),))
    headers = _header_groups(working, root, groups, parser, included_sources)
    choices = [tuple(0 for _ in headers)]
    choices.extend(
        tuple(branch if index == selected else 0 for index in range(len(headers)))
        for selected, group in enumerate(headers)
        for branch in range(1, len(group.branches))
    )
    return (
        _project_view(working, headers, choice, parser, included_sources)
        for choice in choices
    )


def _project_view(
    source: bytes,
    headers: list[_Conditional],
    choice: tuple[int, ...],
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...] = (),
) -> CParseView:
    """Construct one coordinate-preserving header and statement projection.

    Parameters
    ----------
    source : bytes
        C-only source at original offsets.
    headers : list[_Conditional]
        Disjoint complete-header groups.
    choice : tuple[int, ...]
        Selected written branch for each header group.
    parser : tree_sitter.Parser
        Package-local C grammar parser.

    included_sources : tuple[tuple[bytes, int], ...], optional
        Captured header bytes and original or probe-adjusted availability.

    Returns
    -------
    CParseView
        Signature buffer and its independently parsed syntax tree.
    """
    spans = [span for group in headers for span in group.directives]
    spans.extend(
        span
        for group, selected in zip(headers, choice, strict=True)
        for index, span in enumerate(group.branches)
        if index != selected
    )
    signature_source = _statement_projection(
        _blank(source, spans), parser, included_sources
    )
    return CParseView(
        signature_source, _parse_c_source(signature_source, parser, included_sources)
    )
