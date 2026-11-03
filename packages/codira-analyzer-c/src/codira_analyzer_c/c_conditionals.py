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
    branch_condition : str | None, optional
        Written conditional directive selected for this recovery view.
    coverage_incomplete : bool, optional
        Whether this view is part of incomplete source coverage.

    Returns
    -------
    None
        Equal-coordinate source and grammar view; callers retain header context.
    """

    source: bytes
    root: Node
    branch_condition: str | None = None
    coverage_incomplete: bool = False


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
    unsupported_cxx = _has_unsupported_cxx_function(base, source)
    projected_partial = base.text is not None and base.text != source
    has_conditional_nodes = any(
        node.type in {"preproc_if", "preproc_ifdef"} for node in _nodes(base)
    )
    if not base.has_error and not unsupported_cxx and not has_conditional_nodes:
        return iter((CParseView(source, base),))
    working = base.text if projected_partial else _c_language_source(source, base)
    if working is None:
        return iter((CParseView(source, base),))
    root = base if projected_partial else parser.parse(working).root_node
    groups = _conditionals(working, root, parser)
    if groups is None:
        subtree_views = _clean_subtree_views(source, root, parser, included_sources)
        return iter(subtree_views or (CParseView(source, base),))
    headers = _header_groups(working, root, groups, parser, included_sources)
    choices = [tuple(0 for _ in headers)]
    choices.extend(
        tuple(branch if index == selected else 0 for index in range(len(headers)))
        for selected, group in enumerate(headers)
        for branch in range(1, len(group.branches))
    )
    header_views = tuple(
        _project_view(working, headers, choice, parser, included_sources)
        for choice in choices
    )
    if not unsupported_cxx and not any(view.root.has_error for view in header_views):
        if not headers and groups:
            branch_views = _conditional_branch_views(
                working,
                _groups_outside_function_bodies(root, groups),
                parser,
                included_sources,
            )
            if branch_views:
                return iter(branch_views)
        if projected_partial:
            return iter((CParseView(source, base),))
        return iter(header_views)
    branch_views = _conditional_branch_views(
        working,
        _groups_outside_function_bodies(root, groups),
        parser,
        included_sources,
    )
    if branch_views:
        return iter(branch_views)
    subtree_views = _clean_subtree_views(source, root, parser, included_sources)
    if subtree_views:
        return iter(subtree_views)
    return iter(header_views)


def _groups_outside_function_bodies(
    root: Node, groups: list[_Conditional]
) -> list[_Conditional]:
    """Keep statement alternatives out of declaration-branch recovery.

    Parameters
    ----------
    root : tree_sitter.Node
        Translation-unit parse tree.
    groups : list[_Conditional]
        Balanced conditional groups with source byte ranges.

    Returns
    -------
    list[_Conditional]
        Groups not nested inside a function body.
    """
    bodies = [
        body
        for node in _nodes(root)
        if node.type == "function_definition"
        and (body := node.child_by_field_name("body")) is not None
    ]
    return [
        group
        for group in groups
        if not any(body.start_byte <= group.start < body.end_byte for body in bodies)
    ]


def _has_unsupported_cxx_function(root: Node, source: bytes) -> bool:
    """Detect namespace syntax that the C grammar recovers as a function.

    Parameters
    ----------
    root : tree_sitter.Node
        Parsed tree for the source file.
    source : bytes
        Original source bytes for exact token inspection.

    Returns
    -------
    bool
        Whether a function-shaped node begins with C++ ``namespace`` syntax.
    """
    return any(
        node.type == "function_definition"
        and (type_node := node.child_by_field_name("type")) is not None
        and source[type_node.start_byte : type_node.end_byte] == b"namespace"
        for node in _nodes(root)
    )


def _clean_subtree_views(
    source: bytes,
    root: Node,
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> tuple[CParseView, ...]:
    """Retain independent file-scope nodes outside parser error subtrees.

    Parameters
    ----------
    source : bytes
        Original source bytes and coordinate system.
    root : tree_sitter.Node
        Partial translation unit with recoverable siblings.
    parser : tree_sitter.Parser
        C parser used to validate isolated node projections.
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers and their original availability boundaries.

    Returns
    -------
    tuple[CParseView, ...]
        Source-coordinate views for independently clean declarations and
        definitions. Every returned view signals incomplete file coverage.
    """
    # Once preprocessing directives participate, a seemingly clean sibling can
    # depend on macro state that this isolated view cannot establish.
    if (
        re.search(rb"(?m)^\s*#", source)
        or b"_Pragma(" in source
        or b"__pragma(" in source
    ):
        return ()
    declarations = {
        "declaration",
        "function_definition",
        "type_definition",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
        "preproc_def",
        "preproc_function_def",
        "preproc_call",
    }
    wrappers = {
        "preproc_if",
        "preproc_ifdef",
        "preproc_else",
        "preproc_elif",
        "preproc_elifdef",
        "linkage_specification",
        "declaration_list",
    }
    candidates: list[Node] = []
    pending = list(reversed(root.children))
    while pending:
        node = pending.pop()
        if node.type in declarations:
            if not node.has_error:
                candidates.append(node)
            continue
        if node.type in wrappers:
            excluded = {
                node.child_by_field_name("condition"),
                node.child_by_field_name("name"),
            }
            pending.extend(
                child
                for child in reversed(node.named_children)
                if child not in excluded
            )
    type_declaration_nodes = {
        "type_definition",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
    }
    has_clean_type_declaration = any(
        node.type in type_declaration_nodes
        or any(child.type in type_declaration_nodes for child in _nodes(node))
        for node in candidates
    )
    if not has_clean_type_declaration and not any(
        node.type == "function_definition" for node in candidates
    ):
        return ()
    views: list[CParseView] = []
    for node in candidates:
        end_byte = node.end_byte
        if node.type in {"struct_specifier", "union_specifier", "enum_specifier"}:
            following_semicolon = next(
                (
                    child
                    for child in (() if node.parent is None else node.parent.children)
                    if child.start_byte == node.end_byte and child.type == ";"
                ),
                None,
            )
            if following_semicolon is not None:
                end_byte = following_semicolon.end_byte
        projected = _blank(
            source,
            [(0, node.start_byte), (end_byte, len(source))],
        )
        tree = _parse_c_source(projected, parser, included_sources)
        if not tree.has_error:
            views.append(CParseView(projected, tree, coverage_incomplete=True))
    return tuple(views)


def _conditional_branch_views(
    source: bytes,
    groups: list[_Conditional],
    parser: Parser,
    included_sources: tuple[tuple[bytes, int], ...],
) -> tuple[CParseView, ...]:
    """Parse each written branch of top-level groups in isolation.

    Parameters
    ----------
    source : bytes
        Original-coordinate source buffer.
    groups : list[_Conditional]
        Balanced source conditionals.
    parser : tree_sitter.Parser
        C parser for each branch projection.
    included_sources : tuple[tuple[bytes, int], ...]
        Captured headers and their original availability boundaries.

    Returns
    -------
    tuple[CParseView, ...]
        Linear covering views for top-level written alternatives, including
        views that remain partial because their syntax is outside C grammar.
    """
    parents = [
        group
        for group in groups
        if group.end > group.start and not _is_include_guard(source, group)
    ]
    top_level = [
        group
        for group in parents
        if not any(
            outer.start < group.start and group.end < outer.end for outer in parents
        )
    ]
    if not top_level:
        return ()
    groups_with_declarations = [
        group
        for group in top_level
        if any(
            _branch_has_declaration(source[start:end], parser)
            for start, end in group.branches
        )
    ]
    if not groups_with_declarations:
        return ()
    top_level = groups_with_declarations
    alternatives = [
        tuple(range(len(group.branches) + int(not group.has_else)))
        for group in top_level
    ]
    valid_alternatives: list[tuple[int, ...]] = []
    for group, branches in zip(top_level, alternatives, strict=True):
        valid: list[int] = []
        for branch in branches:
            if branch >= len(group.branches):
                valid.append(branch)
                continue
            start, end = group.branches[branch]
            fragment = source[start:end]
            if (
                not _unsupported_cxx_syntax(fragment)
                and _branch_has_declaration(fragment, parser)
                and not _parse_c_source(
                    fragment, parser, _slice_inputs(included_sources, start, end)
                ).has_error
            ):
                valid.append(branch)
        valid_alternatives.append(tuple(valid))
    defaults = tuple(
        valid[0] if valid else (branches[-1] if branches else 0)
        for valid, branches in zip(valid_alternatives, alternatives, strict=True)
    )
    selections = [defaults]
    selections.extend(
        tuple(
            branch if index == selected else defaults[index]
            for index in range(len(top_level))
        )
        for selected, branches in enumerate(alternatives)
        for branch in branches
        if branch != defaults[selected]
    )
    combination_count = 1
    for branches in alternatives:
        combination_count *= len(branches)
    coverage_incomplete = combination_count > len(selections) or any(
        len(valid) < len(branches)
        for valid, branches in zip(valid_alternatives, alternatives, strict=True)
    )
    views: list[CParseView] = []
    for selection in selections:
        complete_alternatives = True
        for group_index, (group, selected) in enumerate(
            zip(top_level, selection, strict=True)
        ):
            if selected not in valid_alternatives[group_index]:
                complete_alternatives = False
                start, end = group.branches[selected]
                condition = _branch_condition(source, group, selected)
                views.append(
                    CParseView(
                        source,
                        parser.parse(source[start:end]).root_node,
                        condition,
                        True,
                    )
                )
                break
        if not complete_alternatives:
            continue
        projected = source
        for group, selected in zip(top_level, selection, strict=True):
            spans = list(group.directives)
            spans.extend(
                span for index, span in enumerate(group.branches) if index != selected
            )
            projected = _blank(projected, spans)
        tree = _parse_c_source(projected, parser, included_sources)
        selected_conditions = [
            _branch_condition(source, group, selected)
            for group, selected in zip(top_level, selection, strict=True)
        ]
        views.append(
            CParseView(
                projected,
                tree,
                "; ".join(selected_conditions) or None,
                coverage_incomplete,
            )
        )
    return tuple(views)


def _branch_has_declaration(fragment: bytes, parser: Parser) -> bool:
    """Require source declarations before projecting one conditional group.

    Parameters
    ----------
    fragment : bytes
        One written alternative.
    parser : tree_sitter.Parser
        C parser used to distinguish declarations from preprocessing-only text.

    Returns
    -------
    bool
        Whether the fragment contains a function, declaration, or type node.
    """
    root = parser.parse(fragment).root_node
    return any(
        node.type
        in {
            "declaration",
            "function_definition",
            "type_definition",
            "struct_specifier",
            "union_specifier",
            "enum_specifier",
        }
        for node in _nodes(root)
    )


def _unsupported_cxx_syntax(fragment: bytes) -> bool:
    """Recognize common C++ declarations that C parsing would misclassify.

    Parameters
    ----------
    fragment : bytes
        One source alternative.

    Returns
    -------
    bool
        Whether the text contains a C++ namespace or template introducer.
    """
    return re.search(rb"\bnamespace\b|\btemplate\s*<", fragment) is not None


def _branch_condition(source: bytes, group: _Conditional, branch: int) -> str:
    """Render the source directive associated with one conditional alternative.

    Parameters
    ----------
    source : bytes
        Original conditional source.
    group : _Conditional
        Conditional group containing the alternative.
    branch : int
        Alternative index, including the implicit no-branch choice.

    Returns
    -------
    str
        Written directive text or the explicit label for an implicit branch.
    """
    if branch >= len(group.branches):
        return "implicit no-branch alternative"
    directive = group.directives[min(branch, len(group.directives) - 2)]
    return source[directive[0] : directive[1]].decode("utf-8", errors="replace").strip()


def _is_include_guard(source: bytes, group: _Conditional) -> bool:
    """Recognize the conventional file-wide ``#ifndef`` include guard.

    Parameters
    ----------
    source : bytes
        Original source buffer.
    group : _Conditional
        Balanced conditional under inspection.

    Returns
    -------
    bool
        Whether the first alternative defines the same identifier used by an
        opening ``#ifndef`` directive.
    """
    opening = source[group.directives[0][0] : group.directives[0][1]]
    match = re.match(rb"\s*#\s*ifndef\s+([A-Za-z_][A-Za-z_0-9]*)\b", opening)
    if match is None or not group.branches:
        return False
    start, end = group.branches[0]
    body = source[start:end]
    definition = re.match(
        rb"(?:\s|/\*.*?\*/|//[^\n]*(?:\n|$))*#\s*define\s+([A-Za-z_][A-Za-z_0-9]*)\b",
        body,
        flags=re.DOTALL,
    )
    return definition is not None and definition[1] == match[1]


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
