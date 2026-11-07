"""Map variable-width syntax expansions back to original C++ source positions.

Parameters
----------
None

Returns
-------
None
    Supplies syntax nodes with original coordinates and explicit synthetic text.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

from tree_sitter import Node, Point


@dataclass(eq=False)
class _ProjectedNode:
    """Retain the extraction surface of a node after source expansion.

    Parameters
    ----------
    type : str
        Grammar node kind.
    start_byte, end_byte : int
        Original source span.
    start_point, end_point : tree_sitter.Point
        Original row and byte-column positions.
    has_error, is_error, is_missing : bool
        Provider diagnostics, retained without modification.
    text : bytes
        Original-coordinate parser layout, retaining licensed annotation blanks.
    syntax_text : bytes
        Actual parsed text, for expanded namespace identities only.
    children, named_children : list[_ProjectedNode], optional
        Projected child nodes in provider order.
    parent, prev_sibling : _ProjectedNode or None, optional
        Structural links in the projected tree.
    fields : dict[str, _ProjectedNode], optional
        Provider field names mapped to children.
    field_names : list[str or None], optional
        Field names by child position.
    macro_hint : str or None, optional
        Source invocation retained on an expanded statement node.
    macro_arguments : tree_sitter.Node or None, optional
        Separately parsed original arguments erased by a selected replacement.
        Only lexical call extraction visits this detached source tree.

    Returns
    -------
    None
        Constructs a tree-local node without shared mutable parser state.
    """

    type: str
    start_byte: int
    end_byte: int
    start_point: Point
    end_point: Point
    has_error: bool
    is_error: bool
    is_missing: bool
    text: bytes
    syntax_text: bytes
    children: list[_ProjectedNode] = field(default_factory=list)
    named_children: list[_ProjectedNode] = field(default_factory=list)
    parent: _ProjectedNode | None = None
    prev_sibling: _ProjectedNode | None = None
    fields: dict[str, _ProjectedNode] = field(default_factory=dict)
    field_names: list[str | None] = field(default_factory=list)
    macro_hint: str | None = None
    macro_arguments: Node | None = None

    def child_by_field_name(self, name: str) -> _ProjectedNode | None:
        """Find the first child carrying a provider field.

        Parameters
        ----------
        name : str
            Provider field name.

        Returns
        -------
        _ProjectedNode or None
            Matching child, when present.
        """
        return self.fields.get(name)

    def field_name_for_child(self, child_index: int) -> str | None:
        """Read a provider field by child position.

        Parameters
        ----------
        child_index : int
            Zero-based child position.

        Returns
        -------
        str or None
            Field name, or None outside the child range.
        """
        return (
            self.field_names[child_index]
            if 0 <= child_index < len(self.field_names)
            else None
        )


SyntaxNode = Node | _ProjectedNode


@dataclass(frozen=True)
class _SourceProjection:
    """Bind expanded segments to their original invocation spans.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned buffer before expansion.
    expanded : bytes
        Buffer passed to tree-sitter.
    segments : tuple[tuple[int, int, int, int, bool], ...]
        Expanded start/end, original start/end and replacement marker.
    starts : tuple[int, ...]
        Expanded segment starts for binary search.
    lines : tuple[int, ...]
        Original line starts, measured in bytes.

    Returns
    -------
    None
        Immutable mapping scoped to one parse.
    """

    source: bytes
    expanded: bytes
    segments: tuple[tuple[int, int, int, int, bool], ...]
    starts: tuple[int, ...]
    lines: tuple[int, ...]

    def offset(self, value: int, *, end: bool = False) -> int:
        """Map a parsed offset, enclosing synthetic bytes in their invocation.

        Parameters
        ----------
        value : int
            Offset in the expanded buffer.
        end : bool, optional
            Whether this is an exclusive end boundary.

        Returns
        -------
        int
            Original byte offset.
        """
        first, last, original, original_end, replaced = self.segments[
            bisect_right(self.starts, value) - 1
        ]
        if value == last:
            return original_end
        if not replaced:
            return original + value - first
        return original_end if end and value > first else original

    def point(self, value: int) -> Point:
        """Resolve an original offset to its row and byte column.

        Parameters
        ----------
        value : int
            Original byte offset.

        Returns
        -------
        tree_sitter.Point
            Zero-based row and byte column, including UTF-8 and CRLF input.
        """
        row = bisect_right(self.lines, value) - 1
        return Point(row, value - self.lines[row])

    def tree(self, root: SyntaxNode) -> _ProjectedNode:
        """Project a parsed tree iteratively without recursive depth limits.

        Parameters
        ----------
        root : SyntaxNode
            Root parsed from this projection's expanded buffer.

        Returns
        -------
        _ProjectedNode
            Equivalent tree with original coordinates and namespace syntax text.
        """
        layout = self._parser_layout(root)
        projected = self.node(root, source_layout=layout)
        pending = [(root, projected)]
        while pending:
            native, parent = pending.pop()
            previous = None
            named = set(native.named_children)
            children: Sequence[SyntaxNode] = native.children
            for index, child in enumerate(children):
                mapped = self.node(child, source_layout=layout)
                mapped.parent = parent
                mapped.prev_sibling = previous
                parent.children.append(mapped)
                if child in named:
                    parent.named_children.append(mapped)
                name = native.field_name_for_child(index)
                parent.field_names.append(name)
                if name is not None:
                    parent.fields.setdefault(name, mapped)
                pending.append((child, mapped))
                previous = mapped
        return projected

    def _parser_layout(self, root: SyntaxNode) -> bytes:
        """Retain parser annotation blanks only across unchanged physical spelling.

        Parameters
        ----------
        root : SyntaxNode
            Parsed root whose coordinate-aligned text may erase annotations.

        Returns
        -------
        bytes
            Original-width layout; generated segments and nonblank rewrites retain
            their original bytes. Unavailable or misaligned views authorize no mask.
        """
        parsed = root.text
        if parsed is None or len(parsed) != root.end_byte - root.start_byte:
            return self.source
        layout: bytearray | None = None
        whitespace = b" \t\r\n\f"
        for first, last, original, original_end, replaced in self.segments:
            if (
                replaced
                or last - first != original_end - original
                or self.expanded[first:last] != self.source[original:original_end]
            ):
                continue
            start, end = max(first, root.start_byte), min(last, root.end_byte)
            if start >= end:
                continue
            raw = self.expanded[start:end]
            view = parsed[start - root.start_byte : end - root.start_byte]
            if raw == view:
                continue
            for index, (before, after) in enumerate(zip(raw, view, strict=True)):
                if after in b" \t\f" and before not in whitespace:
                    if layout is None:
                        layout = bytearray(self.source)
                    layout[original + start - first + index] = after
        return self.source if layout is None else bytes(layout)

    def node(
        self, node: SyntaxNode, *, source_layout: bytes | None = None
    ) -> _ProjectedNode:
        """Copy scalar provider data with original byte and point boundaries.

        Parameters
        ----------
        node : SyntaxNode
            Native syntax node.
        source_layout : bytes or None, optional
            Original-width parser layout with independently retained blanks.

        Returns
        -------
        _ProjectedNode
            Node whose child and parent links are populated separately.
        """
        start = self.offset(node.start_byte)
        end = self.offset(node.end_byte, end=True)
        return _ProjectedNode(
            type=node.type,
            start_byte=start,
            end_byte=end,
            start_point=self.point(start),
            end_point=self.point(end),
            has_error=node.has_error,
            is_error=node.is_error,
            is_missing=node.is_missing,
            text=(self.source if source_layout is None else source_layout)[start:end],
            syntax_text=node.syntax_text
            if isinstance(node, _ProjectedNode)
            else self.expanded[node.start_byte : node.end_byte],
        )


def _source_projection(
    source: bytes, replacements: list[tuple[int, int, bytes]]
) -> _SourceProjection:
    """Construct a mapping from ordered, nonoverlapping invocation replacements.

    Parameters
    ----------
    source : bytes
        Coordinate-aligned input buffer.
    replacements : list[tuple[int, int, bytes]]
        Original start/end offsets and nonempty expansion bytes.

    Returns
    -------
    _SourceProjection
        Expanded bytes and their original source mapping.

    Raises
    ------
    ValueError
        If a replacement is empty, overlaps another or exceeds the source.
    """
    parts: list[bytes] = []
    segments: list[tuple[int, int, int, int, bool]] = []
    cursor = size = 0
    for start, end, value in replacements:
        if not value or not cursor <= start < end <= len(source):
            raise ValueError("Invalid source projection replacement")
        if cursor < start:
            parts.append(source[cursor:start])
            segments.append((size, size + start - cursor, cursor, start, False))
            size += start - cursor
        parts.append(value)
        segments.append((size, size + len(value), start, end, True))
        size += len(value)
        cursor = end
    parts.append(source[cursor:])
    segments.append((size, size + len(source) - cursor, cursor, len(source), False))
    return _SourceProjection(
        source=source,
        expanded=b"".join(parts),
        segments=tuple(segments),
        starts=tuple(segment[0] for segment in segments),
        lines=(0, *(i + 1 for i, byte in enumerate(source) if byte == 10)),
    )
