"""Typed status declarations for the optional automatic-indexing daemon.

The declarations are runtime-neutral: watcher, scheduler, and service
implementations will populate them in later slices.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class DaemonState(StrEnum):
    """Observable lifecycle states for one daemon instance.

    Parameters
    ----------
    None

    Returns
    -------
    None

    Notes
    -----
    ``WATCHING`` means the daemon is ready for filesystem notifications;
    ``INDEXING`` means it is reconciling a debounced change batch.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    WATCHING = "watching"
    INDEXING = "indexing"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class DaemonStatus:
    """Report durable daemon lifecycle and reconciliation state.

    Parameters
    ----------
    state : DaemonState
        Current observable lifecycle state.
    pending_reconciliation : bool
        Whether a change observed during indexing requires one follow-up run.
    last_reconciled_commit : str | None
        Git commit identity reconciled by the most recent completed index run.
    last_success_at : datetime | None
        Completion time for the most recent successful index run.
    last_failure_at : datetime | None
        Completion time for the most recent failed index run.
    last_error : str | None
        Stable diagnostic for the most recent failed index run.

    Returns
    -------
    None

    Notes
    -----
    This declaration does not persist or mutate status. Later runtime slices
    own storage, service-manager integration, and timestamp generation.
    """

    state: DaemonState
    pending_reconciliation: bool = False
    last_reconciled_commit: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_error: str | None = None
