"""Discover source-backed assertion macros without selecting preprocessing branches.

Parameters
----------
None

Returns
-------
None
    Candidate discovery only; ordered context selection still licenses expansion.
"""

from collections.abc import Mapping

from .cpp_macro_context import _definition, _directives
from .cpp_macro_expansion import _macro_tokens


def statement_invocations(
    source: bytes, captures: Mapping[str, bytes]
) -> tuple[tuple[int, int, bytes], ...]:
    """Locate complete invocations of captured function-like assertion macros.

    Parameters
    ----------
    source : bytes
        Original translation unit, including physical invocation positions.
    captures : Mapping[str, bytes]
        Source and literal include snapshots used by ordered context selection.

    Returns
    -------
    tuple[tuple[int, int, bytes], ...]
        Nonoverlapping start/end/name candidates outside directives and literals.

    Raises
    ------
    ValueError
        If an invocation is unclosed or the existing lexical bounds are exceeded.
    """
    names = set()
    for content in captures.values():
        if b"static_assert" not in content:
            continue
        for _, _, kind, payload in _directives(content):
            if kind != b"define":
                continue
            name, definition = _definition(payload)
            if definition is None or definition.parameters is None:
                continue
            tokens = _macro_tokens(definition.replacement)
            if tokens and tokens[0].spelling == b"static_assert":
                names.add(name)
    if not names or not any(name in source for name in names):
        return ()
    protected = [(a, b) for a, b, _, _ in _directives(source)]
    tokens = _macro_tokens(source)
    result = []
    covered = -1
    for index, token in enumerate(tokens[:-1]):
        if (
            index <= covered
            or token.spelling not in names
            or tokens[index + 1].spelling != b"("
            or any(a <= token.start < b for a, b in protected)
        ):
            continue
        depth = 0
        for closing in range(index + 1, len(tokens)):
            spelling = tokens[closing].spelling
            depth += int(spelling == b"(") - int(spelling == b")")
            if depth == 0:
                result.append((token.start, tokens[closing].end, token.spelling))
                covered = closing
                break
        else:
            raise ValueError("unclosed statement macro invocation")
    return tuple(result)
