"""Project source-evaluated root activity without inventing physical spelling.

Parameters
----------
None

Returns
-------
None
    Bounded coordinate views; unknown selected conditions retain original syntax.
"""

from collections.abc import Sequence
from bisect import bisect_right
from dataclasses import replace

from .cpp_macro_context import SourceActivity
from .cpp_macro_projection import MacroProjection, SourceSegment

_CONDITIONALS = frozenset(
    {b"if", b"ifdef", b"ifndef", b"elif", b"elifdef", b"elifndef", b"else", b"endif"}
)


def project_root_activity(
    projection: MacroProjection,
    activity: Sequence[SourceActivity],
    *,
    retained_regions: Sequence[tuple[int, int]] = (),
) -> MacroProjection:
    """Blank only source regions licensed by a fully determined primary walk.

    Parameters
    ----------
    projection : MacroProjection
        Actual original bytes and already selected macro expansions.
    activity : collections.abc.Sequence[SourceActivity]
        Ordered primary-source intervals from the same bounded context walk.
    retained_regions : collections.abc.Sequence[tuple[int, int]], optional
        Proven single guarded runtime continuations. Their ordinary source stays
        visible only when the enclosing source region is certainly active.

    Returns
    -------
    MacroProjection
        Coordinate-preserving view with unchanged spelling intervals separated
        from activity blanks. Unknown activity returns the original projection.

    Raises
    ------
    ValueError
        If intervals are invalid, incomplete or overlap selected replacements.

    Notes
    -----
    No condition is evaluated here. Native conditional answers are not inputs.
    The walk bounds the number of intervals by its directive-event budget.
    """
    cursor = 0
    masks: list[tuple[int, int]] = []
    unknown = False
    active_boundaries = {end for _, end, active, _ in activity if active is True}
    retained = sorted(
        {
            (first, last)
            for first, last in retained_regions
            if first in active_boundaries
        }
    )
    retained_starts = [first for first, _ in retained]
    for first, last, active, directive in activity:
        if first != cursor or not first < last <= len(projection.original):
            raise ValueError("invalid root activity interval")
        cursor = last
        unknown |= active is None
        position = bisect_right(retained_starts, first) - 1
        preserve = directive is None and position >= 0 and last <= retained[position][1]
        if (active is False and not preserve) or directive in _CONDITIONALS:
            if masks and masks[-1][1] == first:
                masks[-1] = (masks[-1][0], last)
            else:
                masks.append((first, last))
    if cursor != len(projection.original):
        raise ValueError("incomplete root activity intervals")
    if unknown or not masks:
        return projection
    if projection.masked_spans or projection.coordinate_segments:
        raise ValueError("root activity view already applied")
    output = bytearray(projection.source)
    unchanged: list[SourceSegment] = []
    coordinates: list[tuple[int, int, int]] = []
    covered = 0
    index = 0
    for segment in projection.original_segments:
        first, last = segment.original_span
        cursor = first
        while index < len(masks) and masks[index][1] <= first:
            index += 1
        current = index
        while current < len(masks) and masks[current][0] < last:
            left, right = max(first, masks[current][0]), min(last, masks[current][1])
            if cursor < left:
                start = segment.projected_start + cursor - first
                unchanged.append(SourceSegment(start, (cursor, left)))
                coordinates.append((start, cursor, left))
            start = segment.projected_start + left - first
            coordinates.append((start, left, right))
            for offset in range(start, start + right - left):
                if output[offset] not in (10, 13):
                    output[offset] = 32
            covered += right - left
            cursor = right
            current += 1
        if cursor < last:
            start = segment.projected_start + cursor - first
            unchanged.append(SourceSegment(start, (cursor, last)))
            coordinates.append((start, cursor, last))
    if covered != sum(last - first for first, last in masks):
        raise ValueError("root activity overlaps a selected macro replacement")
    return replace(
        projection,
        source=bytes(output),
        original_segments=tuple(unchanged),
        coordinate_segments=tuple(coordinates),
        masked_spans=tuple(masks),
    )
