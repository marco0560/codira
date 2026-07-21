"""Provide small shared utility helpers.

Responsibilities
----------------
- Provide dependency-free helpers shared by multiple Codira layers.

Design principles
-----------------
Helpers in this module must remain generic and must not encode backend-specific
policy.

Architectural role
------------------
This module belongs to the **utility layer** and avoids encroaching on
domain-specific modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

__all__ = ["iter_batched"]


def iter_batched[Item](
    values: Sequence[Item],
    *,
    batch_size: int,
) -> Iterator[tuple[Item, ...]]:
    """
    Yield fixed-size tuples from one ordered sequence.

    Parameters
    ----------
    values : collections.abc.Sequence[Item]
        Ordered values to partition.
    batch_size : int
        Positive maximum number of values in each yielded tuple.

    Yields
    ------
    tuple[Item, ...]
        Non-empty batches preserving the input order.

    Raises
    ------
    ValueError
        Raised when ``batch_size`` is not positive.
    """
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)
    for start in range(0, len(values), batch_size):
        yield tuple(values[start : start + batch_size])
