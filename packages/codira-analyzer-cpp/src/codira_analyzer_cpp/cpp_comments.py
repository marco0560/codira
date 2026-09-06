"""C++ comment and Doxygen attachment helpers.

Responsibilities
----------------
- Associate leading comments with C++ syntax nodes deterministically.
- Restrict emitted documentation to explicit Doxygen comment forms.

Architectural role
------------------
This module separates comment ownership from C++ tree traversal and artifact
construction while remaining package-local.
"""

from __future__ import annotations

from collections.abc import Sequence

from tree_sitter import Node

from .cpp_syntax import _comment_to_doxygen_text, _comment_to_summary, _node_text


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
