"""Persist immutable paired benchmark attempts and resumable campaign state."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import hashlib
import json
import os
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scripts.agent_efficiency.contracts import (
    ContractError,
    canonical_fingerprint,
    validate_document,
)

if TYPE_CHECKING:
    from pathlib import Path

STATE_VERSION = "1.0"
ASSISTANCE_MODES = ("baseline", "codira-mcp")


class CampaignStateError(ValueError):
    """Report an invalid campaign state, record, or resume request.

    Parameters
    ----------
    detail : str
        Deterministic error detail without raw agent evidence.

    Returns
    -------
    None
        The exception carries the validation detail.
    """


@dataclass(frozen=True)
class ScheduledAttempt:
    """Describe one pre-randomized member of a paired benchmark schedule.

    Parameters
    ----------
    task_id : str
        Frozen public task identity.
    repetition : int
        One-based repetition number.
    assistance_mode : str
        Baseline or required-Codira-MCP variant.
    attempt_id : str
        Stable unique identity persisted with the result.
    pair_id : str
        Stable identity shared by both variants of a repetition.

    Returns
    -------
    None
        Instances are immutable schedule records.
    """

    task_id: str
    repetition: int
    assistance_mode: str
    attempt_id: str
    pair_id: str


def build_paired_schedule(
    task_ids: Sequence[str], repetitions: int, seed: int
) -> tuple[ScheduledAttempt, ...]:
    """Build a deterministic, randomized order for complete task pairs.

    Parameters
    ----------
    task_ids : Sequence[str]
        Unique registered task identities.
    repetitions : int
        Positive number of baseline/MCP pairs for each task.
    seed : int
        Persisted pseudo-random seed controlling pair and within-pair order.

    Returns
    -------
    tuple[ScheduledAttempt, ...]
        Every task/repetition contains exactly one baseline and one MCP run.

    Raises
    ------
    CampaignStateError
        If task identities or repetition count are invalid.
    """

    normalized = tuple(sorted(task_ids))
    if not normalized or len(set(normalized)) != len(normalized):
        raise CampaignStateError("task_ids must be non-empty and unique")
    if repetitions < 1:
        raise CampaignStateError("repetitions must be positive")
    generator = random.Random(seed)
    pairs = [
        (task_id, repetition)
        for task_id in normalized
        for repetition in range(1, repetitions + 1)
    ]
    generator.shuffle(pairs)
    schedule: list[ScheduledAttempt] = []
    for task_id, repetition in pairs:
        modes = list(ASSISTANCE_MODES)
        generator.shuffle(modes)
        pair_id = f"{task_id}-r{repetition:02d}"
        for mode in modes:
            schedule.append(
                ScheduledAttempt(
                    task_id,
                    repetition,
                    mode,
                    f"{pair_id}-{mode}",
                    pair_id,
                )
            )
    return tuple(schedule)


def _canonical_json(document: Mapping[str, object]) -> bytes:
    """Serialize one evidence document canonically.

    Parameters
    ----------
    document : Mapping[str, object]
        JSON-compatible evidence mapping.

    Returns
    -------
    bytes
        UTF-8 canonical JSON bytes.
    """

    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(document: Mapping[str, object]) -> str:
    """Return a SHA-256 checksum for one canonical evidence mapping.

    Parameters
    ----------
    document : Mapping[str, object]
        JSON-compatible evidence mapping.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """

    return hashlib.sha256(_canonical_json(document)).hexdigest()


def _atomic_write(path: Path, document: Mapping[str, object]) -> None:
    """Write one JSON record atomically without overwriting prior evidence.

    Parameters
    ----------
    path : pathlib.Path
        Final absent record path.
    document : Mapping[str, object]
        JSON-compatible record to persist.

    Returns
    -------
    None
        The final path is atomically installed after durable file data.

    Raises
    ------
    CampaignStateError
        If a record already exists or the write cannot be completed.
    """

    if path.exists():
        raise CampaignStateError(f"immutable record already exists: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(_canonical_json(document) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise CampaignStateError(f"immutable record already exists: {path.name}")
        temporary.replace(path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        raise CampaignStateError(
            f"cannot atomically write {path.name}: {error}"
        ) from error
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class CampaignStore:
    """Manage one frozen campaign's immutable attempt evidence.

    Parameters
    ----------
    root : pathlib.Path
        Ignored runtime root owned by one campaign.
    campaign_id : str
        Immutable campaign identity.
    configuration : Mapping[str, object]
        Frozen runner/configuration identity used for drift detection.
    schedule : tuple[ScheduledAttempt, ...]
        Pre-randomized complete paired schedule.

    Returns
    -------
    None
        Instances validate identity before loading or storing evidence.
    """

    root: Path
    campaign_id: str
    configuration: Mapping[str, object]
    schedule: tuple[ScheduledAttempt, ...]

    @property
    def configuration_fingerprint(self) -> str:
        """Return the frozen configuration fingerprint.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 identity of the frozen configuration mapping.
        """

        return canonical_fingerprint(self.configuration)

    @property
    def state_path(self) -> Path:
        """Return the campaign state document location.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            The deterministic runtime state path.
        """

        return self.root / "campaign-state.json"

    @property
    def records_root(self) -> Path:
        """Return the immutable result-record directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Directory containing one JSON record per attempted execution.
        """

        return self.root / "records"

    @property
    def preparation_root(self) -> Path:
        """Return the separate assisted-index preparation evidence directory.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Immutable pre-timer preparation records, never result records.
        """

        return self.root / "index-preparation"

    def store_index_preparation(
        self, attempt_id: str, preparation: Mapping[str, object]
    ) -> Path:
        """Atomically retain pre-timer prepared-index evidence for one MCP run.

        Parameters
        ----------
        attempt_id : str
            Scheduled assisted attempt that will consume the prepared index.
        preparation : Mapping[str, object]
            Credential-free preparation metadata including elapsed seconds and
            the initial fixture/index identities.

        Returns
        -------
        pathlib.Path
            Immutable preparation evidence path.

        Raises
        ------
        CampaignStateError
            If the attempt is not assisted or metadata lacks required facts.
        """

        scheduled = self._scheduled(attempt_id)
        if scheduled.assistance_mode != "codira-mcp":
            raise CampaignStateError("index preparation is only valid for codira-mcp")
        required = {
            "elapsed_seconds",
            "fixture_revision",
            "index_fingerprint",
            "tracked_file_count",
            "indexed_file_count",
            "generation",
            "generation_state",
            "partial",
            "failed_file_count",
        }
        if not required <= preparation.keys():
            raise CampaignStateError("index preparation lacks required evidence")
        elapsed = preparation["elapsed_seconds"]
        if (
            not isinstance(elapsed, (int, float))
            or isinstance(elapsed, bool)
            or elapsed < 0
        ):
            raise CampaignStateError("index preparation elapsed_seconds is invalid")
        tracked = preparation["tracked_file_count"]
        indexed = preparation["indexed_file_count"]
        generation = preparation["generation"]
        if (
            not isinstance(tracked, int)
            or isinstance(tracked, bool)
            or tracked < 1
            or not isinstance(indexed, int)
            or isinstance(indexed, bool)
            or indexed < 1
            or indexed > tracked
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
            or preparation["generation_state"] != "ready"
            or preparation["partial"] is not False
            or preparation["failed_file_count"] != 0
        ):
            raise CampaignStateError("index preparation is not usable")
        record = {
            "state_version": STATE_VERSION,
            "configuration_fingerprint": self.configuration_fingerprint,
            "attempt": scheduled.__dict__,
            "preparation": dict(preparation),
            "preparation_fingerprint": _sha256(preparation),
        }
        path = self.preparation_root / f"{attempt_id}.json"
        _atomic_write(path, record)
        return path

    def initialize(self) -> None:
        """Create or validate the frozen campaign state document.

        Parameters
        ----------
        None

        Returns
        -------
        None
            State is created once or verified for deterministic resumption.

        Raises
        ------
        CampaignStateError
            If existing state has a different identity or schedule.
        """

        state = {
            "state_version": STATE_VERSION,
            "campaign_id": self.campaign_id,
            "configuration_fingerprint": self.configuration_fingerprint,
            "schedule": [attempt.__dict__ for attempt in self.schedule],
        }
        if not self.state_path.exists():
            _atomic_write(self.state_path, state)
            return
        existing = self._load_json(self.state_path)
        if existing != state:
            raise CampaignStateError("campaign state differs from frozen configuration")

    def _load_json(self, path: Path) -> dict[str, object]:
        """Load one object-only runtime JSON file.

        Parameters
        ----------
        path : pathlib.Path
            Runtime state or immutable record path.

        Returns
        -------
        dict[str, object]
            Parsed object mapping.

        Raises
        ------
        CampaignStateError
            If the file is malformed or not a JSON object.
        """

        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CampaignStateError(f"cannot load {path.name}: {error}") from error
        if not isinstance(parsed, dict):
            raise CampaignStateError(f"{path.name} must contain a JSON object")
        return parsed

    def _scheduled(self, attempt_id: str) -> ScheduledAttempt:
        """Return the scheduled attempt identified by one stable identifier.

        Parameters
        ----------
        attempt_id : str
            Requested immutable attempt identity.

        Returns
        -------
        ScheduledAttempt
            Registered schedule member.

        Raises
        ------
        CampaignStateError
            If the attempt was never scheduled.
        """

        for attempt in self.schedule:
            if attempt.attempt_id == attempt_id:
                return attempt
        raise CampaignStateError(f"attempt is not in the frozen schedule: {attempt_id}")

    def store_result(
        self,
        attempt_id: str,
        result: Mapping[str, object],
        evidence: Mapping[str, object],
    ) -> Path:
        """Validate and atomically persist one immutable terminal attempt.

        Parameters
        ----------
        attempt_id : str
            Scheduled attempt identity.
        result : Mapping[str, object]
            Schema-valid public run-result record.
        evidence : Mapping[str, object]
            Runtime evidence metadata or raw-evidence reference.

        Returns
        -------
        pathlib.Path
            Atomically installed immutable result record.

        Raises
        ------
        CampaignStateError
            If identity, schema validation, or immutable persistence fails.
        """

        scheduled = self._scheduled(attempt_id)
        try:
            validate_document("run-result", result)
        except ContractError as error:
            raise CampaignStateError(f"invalid run result: {error}") from error
        expected = (self.campaign_id, scheduled.task_id, scheduled.assistance_mode)
        actual = (
            result.get("campaign_id"),
            result.get("task_id"),
            result.get("assistance_mode"),
        )
        if actual != expected or result.get("attempt_id") != attempt_id:
            raise CampaignStateError(
                "run result identity does not match scheduled attempt"
            )
        record = {
            "state_version": STATE_VERSION,
            "configuration_fingerprint": self.configuration_fingerprint,
            "attempt": scheduled.__dict__,
            "result": dict(result),
            "evidence": dict(evidence),
            "evidence_fingerprint": _sha256(evidence),
        }
        path = self.records_root / f"{attempt_id}.json"
        _atomic_write(path, record)
        return path

    def validated_records(self) -> dict[str, dict[str, object]]:
        """Load only complete, schema-valid, identity-matching records.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, dict[str, object]]
            Validated records keyed by scheduled attempt identity.

        Raises
        ------
        CampaignStateError
            If any installed record is malformed, tampered, or drifted.
        """

        self.initialize()
        self.validated_preparation()
        records: dict[str, dict[str, object]] = {}
        if not self.records_root.exists():
            return records
        for path in sorted(self.records_root.glob("*.json")):
            record = self._load_json(path)
            if record.get("state_version") != STATE_VERSION:
                raise CampaignStateError(
                    f"record schema version is invalid: {path.name}"
                )
            if (
                record.get("configuration_fingerprint")
                != self.configuration_fingerprint
            ):
                raise CampaignStateError(f"configuration drift in record: {path.name}")
            attempt = record.get("attempt")
            result = record.get("result")
            evidence = record.get("evidence")
            if (
                not isinstance(attempt, Mapping)
                or not isinstance(result, Mapping)
                or not isinstance(evidence, Mapping)
            ):
                raise CampaignStateError(f"record is incomplete: {path.name}")
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str) or path.name != f"{attempt_id}.json":
                raise CampaignStateError(
                    f"record filename identity is invalid: {path.name}"
                )
            scheduled = self._scheduled(attempt_id)
            if dict(attempt) != scheduled.__dict__:
                raise CampaignStateError(
                    f"record schedule identity is invalid: {path.name}"
                )
            if record.get("evidence_fingerprint") != _sha256(evidence):
                raise CampaignStateError(
                    f"evidence fingerprint is invalid: {path.name}"
                )
            self._validate_record_result(scheduled, result)
            if attempt_id in records:
                raise CampaignStateError(f"duplicate attempt record: {attempt_id}")
            records[attempt_id] = record
        return records

    def validated_preparation(self) -> dict[str, dict[str, object]]:
        """Load only complete, identity-matching index-preparation records.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, dict[str, object]]
            Validated assisted-only preparation records by attempt identity.

        Raises
        ------
        CampaignStateError
            If immutable preparation evidence is malformed or tampered.
        """

        preparations: dict[str, dict[str, object]] = {}
        if not self.preparation_root.exists():
            return preparations
        required = {"elapsed_seconds", "fixture_revision", "index_fingerprint"}
        for path in sorted(self.preparation_root.glob("*.json")):
            record = self._load_json(path)
            if record.get("state_version") != STATE_VERSION:
                raise CampaignStateError(
                    f"preparation schema version is invalid: {path.name}"
                )
            if (
                record.get("configuration_fingerprint")
                != self.configuration_fingerprint
            ):
                raise CampaignStateError(
                    f"configuration drift in preparation: {path.name}"
                )
            attempt = record.get("attempt")
            preparation = record.get("preparation")
            if not isinstance(attempt, Mapping) or not isinstance(preparation, Mapping):
                raise CampaignStateError(f"preparation is incomplete: {path.name}")
            attempt_id = attempt.get("attempt_id")
            if not isinstance(attempt_id, str) or path.name != f"{attempt_id}.json":
                raise CampaignStateError(
                    f"preparation filename identity is invalid: {path.name}"
                )
            scheduled = self._scheduled(attempt_id)
            if (
                scheduled.assistance_mode != "codira-mcp"
                or dict(attempt) != scheduled.__dict__
            ):
                raise CampaignStateError(
                    f"preparation schedule identity is invalid: {path.name}"
                )
            if not required <= preparation.keys():
                raise CampaignStateError(
                    f"preparation lacks required evidence: {path.name}"
                )
            elapsed = preparation["elapsed_seconds"]
            if (
                not isinstance(elapsed, (int, float))
                or isinstance(elapsed, bool)
                or elapsed < 0
            ):
                raise CampaignStateError(
                    f"preparation elapsed_seconds is invalid: {path.name}"
                )
            if record.get("preparation_fingerprint") != _sha256(preparation):
                raise CampaignStateError(
                    f"preparation fingerprint is invalid: {path.name}"
                )
            if attempt_id in preparations:
                raise CampaignStateError(f"duplicate preparation record: {attempt_id}")
            preparations[attempt_id] = record
        return preparations

    def _validate_record_result(
        self, scheduled: ScheduledAttempt, result: Mapping[str, object]
    ) -> None:
        """Validate persisted result schema and scheduled identity.

        Parameters
        ----------
        scheduled : ScheduledAttempt
            Frozen schedule member expected by the record.
        result : Mapping[str, object]
            Parsed run-result mapping.

        Returns
        -------
        None
            Invalid records raise ``CampaignStateError``.
        """

        try:
            validate_document("run-result", result)
        except ContractError as error:
            raise CampaignStateError(f"invalid stored result: {error}") from error
        if (
            result.get("campaign_id") != self.campaign_id
            or result.get("task_id") != scheduled.task_id
            or result.get("attempt_id") != scheduled.attempt_id
            or result.get("assistance_mode") != scheduled.assistance_mode
        ):
            raise CampaignStateError("stored result does not match its schedule")

    def pending_attempts(self) -> tuple[ScheduledAttempt, ...]:
        """Return schedule members with no validated terminal record.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[ScheduledAttempt, ...]
            Attempts that can be run without overwriting evidence.
        """

        complete = self.validated_records()
        return tuple(
            attempt for attempt in self.schedule if attempt.attempt_id not in complete
        )


def run_pending(
    store: CampaignStore,
    execute: Callable[
        [ScheduledAttempt], tuple[Mapping[str, object], Mapping[str, object]]
    ],
) -> tuple[Path, ...]:
    """Run only unrecorded schedule members and atomically retain each result.

    Parameters
    ----------
    store : CampaignStore
        Initialized frozen campaign state.
    execute : Callable[[ScheduledAttempt], tuple[Mapping[str, object], Mapping[str, object]]]
        Injectable runner returning a result and its evidence metadata.

    Returns
    -------
    tuple[pathlib.Path, ...]
        Immutable records newly installed during this invocation.
    """

    written: list[Path] = []
    for attempt in store.pending_attempts():
        result, evidence = execute(attempt)
        written.append(store.store_result(attempt.attempt_id, result, evidence))
    return tuple(written)
