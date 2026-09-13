"""Protected Click Sentinel regression probe derived from upstream tests.

Provenance: pallets/click commit
f58ca3e81424a35626c8a475eb59ab95589008ce,
``tests/test_utils/test_sentinel.py``.  This stdlib-only form preserves the
upstream copy, deepcopy, pickle, and Option-default identity assertions while
remaining runnable in the benchmark image without pytest.
"""
# ruff: noqa: I001

from __future__ import annotations

import copy
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import click
from click._utils import Sentinel, UNSET  # type: ignore[import-not-found]


def main() -> int:
    """Run the upstream-derived singleton identity regression assertions."""

    duplicates = (
        copy.copy,
        copy.deepcopy,
        lambda value: pickle.loads(pickle.dumps(value)),
    )
    for sentinel in Sentinel:
        for duplicate in duplicates:
            assert duplicate(sentinel) is sentinel  # type: ignore[no-untyped-call]
    option = click.Option(["--name"])
    assert option.default is UNSET
    for duplicate in duplicates:
        copied = duplicate(option)
        assert copied.default is UNSET
        assert copied.name == "name"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
