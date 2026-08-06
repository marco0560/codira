"""Repository-local durable status and activity records for the daemon.

Responsibilities
----------------
- Persist the current daemon reconciliation status atomically.
- Append timestamped status-transition records for later reconstruction.

Design principles
-----------------
Daemon observability is repository-local and independent of a platform service
manager. Activity records deliberately contain no changed filesystem paths.

Architectural role
-----------------
This module belongs to the daemon observability layer.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from codira.daemon.models import DaemonState, DaemonStatus
from codira.storage import get_codira_dir

Clock = Callable[[], datetime]
_STATUS_FILENAME = "daemon-status.json"
_ACTIVITY_FILENAME = "daemon-activity.jsonl"


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC time.

    Parameters
    ----------
    None

    Returns
    -------
    datetime
        Current UTC timestamp used for an activity record.
    """
    return datetime.now(UTC)


def _serialize_timestamp(value: datetime | None) -> str | None:
    """Serialize an optional timestamp using an explicit UTC offset.

    Parameters
    ----------
    value : datetime.datetime | None
        Timestamp to serialize.

    Returns
    -------
    str | None
        ISO-8601 timestamp or ``None`` when no timestamp exists.
    """
    return None if value is None else value.isoformat()


def _deserialize_timestamp(value: object) -> datetime | None:
    """Deserialize one optional ISO-8601 timestamp from a status record.

    Parameters
    ----------
    value : object
        JSON value supplied by the status record.

    Returns
    -------
    datetime | None
        Parsed timezone-aware timestamp or ``None``.

    Raises
    ------
    TypeError
        If the value is not a nullable ISO-8601 string.
    ValueError
        If the timestamp has no timezone.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = "daemon status timestamp must be a string or null"
        raise TypeError(msg)
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None:
        msg = "daemon status timestamp must include a timezone"
        raise ValueError(msg)
    return timestamp


def _status_payload(status: DaemonStatus) -> dict[str, object]:
    """Convert an immutable daemon status into its persisted JSON form.

    Parameters
    ----------
    status : codira.daemon.models.DaemonStatus
        Scheduler snapshot to persist.

    Returns
    -------
    dict[str, object]
        Stable JSON-compatible status mapping.
    """
    return {
        "schema_version": 1,
        "state": status.state.value,
        "pending_reconciliation": status.pending_reconciliation,
        "last_reconciled_commit": status.last_reconciled_commit,
        "last_success_at": _serialize_timestamp(status.last_success_at),
        "last_failure_at": _serialize_timestamp(status.last_failure_at),
        "last_error": status.last_error,
    }


def _status_from_payload(payload: object) -> DaemonStatus:
    """Decode and validate one durable daemon-status JSON payload.

    Parameters
    ----------
    payload : object
        Decoded JSON value from the repository-local status file.

    Returns
    -------
    codira.daemon.models.DaemonStatus
        Typed immutable status snapshot.

    Raises
    ------
    TypeError
        If payload fields have incompatible JSON types.
    ValueError
        If the payload does not match the version-one status contract.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        msg = "unsupported daemon status record"
        raise ValueError(msg)
    state_value = payload.get("state")
    pending = payload.get("pending_reconciliation")
    commit = payload.get("last_reconciled_commit")
    error = payload.get("last_error")
    if not isinstance(state_value, str) or not isinstance(pending, bool):
        msg = "invalid daemon status record"
        raise TypeError(msg)
    if commit is not None and not isinstance(commit, str):
        msg = "daemon status commit must be a string or null"
        raise TypeError(msg)
    if error is not None and not isinstance(error, str):
        msg = "daemon status error must be a string or null"
        raise TypeError(msg)
    try:
        state = DaemonState(state_value)
    except ValueError as exception:
        msg = f"unknown daemon status state: {state_value}"
        raise ValueError(msg) from exception
    return DaemonStatus(
        state=state,
        pending_reconciliation=pending,
        last_reconciled_commit=commit,
        last_success_at=_deserialize_timestamp(payload.get("last_success_at")),
        last_failure_at=_deserialize_timestamp(payload.get("last_failure_at")),
        last_error=error,
    )


class DaemonStatusStore:
    """Persist daemon status and append-only activity for one repository.

    Parameters
    ----------
    root : pathlib.Path
        Repository root that owns the ``.codira`` observability records.
    clock : collections.abc.Callable[[], datetime.datetime], optional
        UTC time source used for deterministic activity records.

    Returns
    -------
    None
        The store does not create files until it records a status.
    """

    def __init__(self, root: Path, *, clock: Clock = _utc_now) -> None:
        """Initialize the durable status store for one repository root.

        Parameters
        ----------
        root : pathlib.Path
            Repository root that owns the local daemon records.
        clock : collections.abc.Callable[[], datetime.datetime], optional
            UTC time source used for deterministic activity records.

        Returns
        -------
        None
            The canonical root and clock are retained for later writes.
        """
        self._root = root.resolve()
        self._clock = clock

    @property
    def status_path(self) -> Path:
        """Return the repository-local durable status file path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            ``.codira/daemon-status.json`` below the effective storage root.
        """
        return get_codira_dir(self._root) / _STATUS_FILENAME

    @property
    def activity_path(self) -> Path:
        """Return the repository-local append-only activity file path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            ``.codira/daemon-activity.jsonl`` below the effective storage root.
        """
        return get_codira_dir(self._root) / _ACTIVITY_FILENAME

    def record(self, status: DaemonStatus) -> None:
        """Atomically replace status and append one reconstructable activity row.

        Parameters
        ----------
        status : codira.daemon.models.DaemonStatus
            Immutable scheduler snapshot to persist.

        Returns
        -------
        None
            The snapshot and an activity row are written below ``.codira``.
        """
        payload = _status_payload(status)
        status_path = self.status_path
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=status_path.parent,
            prefix=f".{status_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
        Path(temporary_file.name).replace(status_path)
        activity = {
            "schema_version": 1,
            "recorded_at": self._clock().isoformat(),
            "kind": "status_snapshot",
            "status": payload,
        }
        with self.activity_path.open("a", encoding="utf-8") as activity_file:
            activity_file.write(json.dumps(activity, sort_keys=True))
            activity_file.write("\n")

    def read(self) -> DaemonStatus | None:
        """Read the current durable daemon status when a record exists.

        Parameters
        ----------
        None

        Returns
        -------
        codira.daemon.models.DaemonStatus | None
            Current persisted snapshot, or ``None`` before the daemon records one.

        Raises
        ------
        ValueError
            If the durable status record is unreadable or invalid.
        """
        if not self.status_path.exists():
            return None
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exception:
            msg = "unable to read daemon status record"
            raise ValueError(msg) from exception
        return _status_from_payload(payload)
