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
    partial : bool
        Whether one or more source files failed during this generation.
    failed_file_count : int
        Number of source files that failed during this generation.
    attempted_file_count : int | None
        Number of selected successful and failed files.
    failed_files : list[dict[str, str]] | None
        Attempted hashes and original per-file failure details.
    analysis_fingerprint : str | None
        Digest binding retained failures to their analysis configuration.
    coverage_complete : bool
        Whether analysis and configured coverage have no known gaps.
    Returns
    -------
    None
        Immutable publication metadata.
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
    partial: bool = False
    failed_file_count: int = 0
    attempted_file_count: int | None = None
    failed_files: list[dict[str, str]] | None = None
    analysis_fingerprint: str | None = None
    coverage_complete: bool = True


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
            record = IndexGeneration(**payload)
            if record.state not in {
                "ready",
                "updating",
                "failed",
            } or record.schema_version not in {1, 2}:
                return None
            if record.schema_version == 2 and record.state == "ready":
                failures = record.failed_files or []
                if record.failed_file_count != len(failures) or record.partial != bool(
                    failures
                ):
                    return None
                for failure in failures:
                    if not all(
                        isinstance(failure.get(key), str)
                        for key in (
                            "path",
                            "sha256",
                            "analyzer_name",
                            "error_type",
                            "reason",
                        )
                    ):
                        return None
                    path = failure["path"]
                    if path.startswith("/") or ".." in path.split("/"):
                        return None
        except (OSError, AttributeError, TypeError, ValueError, json.JSONDecodeError):
            return None
        else:
            return record

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
    partial: bool = False,
    failed_file_count: int = 0,
    attempted_file_count: int | None = None,
    failed_files: list[dict[str, str]] | None = None,
    analysis_fingerprint: str | None = None,
    coverage_complete: bool = True,
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
    partial : bool, optional
        Whether one or more source files failed during this generation.
    failed_file_count : int, optional
        Number of source files that failed during this generation.

    attempted_file_count : int | None, optional
        Successful and failed selected files attempted during publication.
    failed_files : list[dict[str, str]] | None, optional
        Relative paths, attempted content hashes, and original failure details.
    analysis_fingerprint : str | None, optional
        Effective configuration and analyzer identity digest.
    coverage_complete : bool, optional
        Whether the selected scope has no analysis or coverage gaps.

    Returns
    -------
    IndexGeneration
        Complete immutable transition record.
    """
    return IndexGeneration(
        schema_version=2,
        generation=generation,
        state=state,
        last_successful_generation=last_successful_generation,
        timestamp=datetime.now(UTC).isoformat(),
        git_commit=git_commit,
        backend_name=backend_name,
        backend_version=backend_version,
        analyzer_inventory=analyzer_inventory,
        indexed_file_count=indexed_file_count,
        partial=partial,
        failed_file_count=failed_file_count,
        attempted_file_count=attempted_file_count,
        failed_files=failed_files,
        analysis_fingerprint=analysis_fingerprint,
        coverage_complete=coverage_complete,
    )
