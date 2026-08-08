"""Tests for durable index-generation publication."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.index_generation import IndexGenerationStore, transition_record
from codira.storage import override_storage_root

if TYPE_CHECKING:
    from pathlib import Path


def test_generation_store_atomically_round_trips_ready_record(tmp_path: Path) -> None:
    """Persist a complete ready handoff below the repository state directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts complete durable record round-tripping.
    """
    store = IndexGenerationStore(tmp_path)
    store.write(
        transition_record(
            generation=2,
            state="ready",
            last_successful_generation=2,
            backend_name="sqlite",
            indexed_file_count=4,
        )
    )

    record = store.read()

    assert record is not None
    assert record.state == "ready"
    assert record.generation == record.last_successful_generation == 2
    assert record.backend_name == "sqlite"


def test_generation_store_treats_corrupt_record_as_unavailable(tmp_path: Path) -> None:
    """Avoid trusting incomplete publication after a crash.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts malformed state never becomes a ready generation.
    """
    store = IndexGenerationStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{broken", encoding="utf-8")

    assert store.read() is None


def test_generation_store_honors_effective_output_root(tmp_path: Path) -> None:
    """Keep generation records isolated by effective output directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository and output roots.

    Returns
    -------
    None
        The test asserts an output-root override receives the durable record.
    """
    root = tmp_path / "repository"
    output = tmp_path / "output"
    root.mkdir()
    with override_storage_root(root, output):
        store = IndexGenerationStore(root)
        store.write(
            transition_record(
                generation=1,
                state="ready",
                last_successful_generation=1,
            )
        )

    assert (output / ".codira" / "index-generation.json").is_file()
    assert not (root / ".codira" / "index-generation.json").exists()
