"""Tests for shared utility helpers."""

from __future__ import annotations

import pytest

from codira.utils import iter_batched


def test_iter_batched_preserves_order_and_keeps_the_final_remainder() -> None:
    """
    Partition ordered values without dropping the final incomplete batch.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts stable ordered tuple batches.
    """
    assert list(iter_batched(("a", "b", "c", "d", "e"), batch_size=2)) == [
        ("a", "b"),
        ("c", "d"),
        ("e",),
    ]


def test_iter_batched_rejects_non_positive_batch_sizes() -> None:
    """
    Reject invalid batch sizes before iterating values.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts an explicit validation error.
    """
    with pytest.raises(ValueError, match="batch_size must be positive"):
        list(iter_batched(("a",), batch_size=0))
