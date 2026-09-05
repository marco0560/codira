"""Durable index-generation publication for repository-local readers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from codira.storage import get_codira_dir

if TYPE_CHECKING:
    from pathlib import Path

IndexGenerationState = Literal["updating", "ready", "failed"]


@dataclass(frozen=True)
class IndexGeneration:
    """Describe one durable index handoff state.

    Parameters
    ----------
    schema_version : int
        Record schema version.
    generation : int
        Monotonically increasing generation number.
    state : {"updating", "ready", "failed"}
        Mutation lifecycle state.
    last_successful_generation : int
        Last fully committed generation.
    timestamp : str
        UTC transition timestamp.
    """

    schema_version: int
    generation: int
    state: IndexGenerationState
    last_successful_generation: int
    timestamp: str
    git_commit: str | None = None
    backend_name: str | None = None
    backend_version: str | None = None
    analyzer_inventory: list[dict[str, object]] | None = None
    indexed_file_count: int | None = None


class IndexGenerationStore:
    """Atomically persist generation records below the effective state root.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective storage root owns the record.
    """

    def __init__(self, root: Path, *, output_root: Path | None = None) -> None:
        """Initialize a store for one repository.

        Parameters
        ----------
        root : pathlib.Path
            Repository root used to resolve the effective state directory.
        """
        self.path = (
            get_codira_dir(root)
            if output_root is None
            else output_root.resolve() / ".codira"
        ) / "index-generation.json"

    def read(self) -> IndexGeneration | None:
        """Read the latest generation record when it is valid.

        Parameters
        ----------
        None

        Returns
        -------
        IndexGeneration | None
            Parsed record, or ``None`` before first publication.
        """
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return IndexGeneration(**payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def write(self, record: IndexGeneration) -> None:
        """Atomically replace the record with one complete JSON document.

        Parameters
        ----------
        record : IndexGeneration
            Transition record to persist.

        Returns
        -------
        None
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(record), sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


def transition_record(  # noqa: PLR0913
    *,
    generation: int,
    state: IndexGenerationState,
    last_successful_generation: int,
    git_commit: str | None = None,
    backend_name: str | None = None,
    backend_version: str | None = None,
    analyzer_inventory: list[dict[str, object]] | None = None,
    indexed_file_count: int | None = None,
) -> IndexGeneration:
    """Build a timestamped generation transition record.

    Parameters
    ----------
    generation : int
        Current transition generation.
    state : {"updating", "ready", "failed"}
        Current transition state.
    last_successful_generation : int
        Last committed generation.
    git_commit : str | None, optional
        Git commit observed after the successful index pass.
    backend_name : str | None, optional
        Active structural backend name.
    backend_version : str | None, optional
        Active structural backend version.
    analyzer_inventory : list[dict[str, object]] | None, optional
        Active analyzer identity inventory.
    indexed_file_count : int | None, optional
        Number of indexed file rows after the pass.

    Returns
    -------
    IndexGeneration
        Complete immutable transition record.
    """
    return IndexGeneration(
        1,
        generation,
        state,
        last_successful_generation,
        datetime.now(UTC).isoformat(),
        git_commit,
        backend_name,
        backend_version,
        analyzer_inventory,
        indexed_file_count,
    )
