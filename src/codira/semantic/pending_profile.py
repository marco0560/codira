"""Opt-in phase evidence for pending embedding population and recovery.

Parameters
----------
None

Returns
-------
None
    Shared diagnostics contain no source text, credentials or embedding vectors.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from types import TracebackType


class PendingEmbeddingProfile:
    """Append phase receipts to a unique invocation journal when opted in.

    Parameters
    ----------
    backend : str
        Structural backend label for attribution.

    Returns
    -------
    None
        No files are written unless CODIRA_EMBEDDING_PROFILE_DIR is configured.
    """

    def __init__(self, backend: str) -> None:
        """Select an isolated journal without truncating earlier attempts.

        Parameters
        ----------
        backend : str
            Structural backend label.

        Returns
        -------
        None
            Creates a unique journal path only for explicit profiling.
        """
        directory = os.environ.get("CODIRA_EMBEDDING_PROFILE_DIR")
        self.path = (
            None
            if not directory
            else Path(directory) / f"{backend}-{uuid4().hex}.jsonl"
        )
        self.backend = backend
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def span(self, phase: str, *, rows: int = 0) -> _PendingEmbeddingSpan:
        """Return a context recording phase time without suppressing failures.

        Parameters
        ----------
        phase : str
            Stable phase label; nested spans are diagnostic and not additive.
        rows : int, optional
            Logical rows processed by this phase.

        Returns
        -------
        _PendingEmbeddingSpan
            Measurement context that preserves the original processing failure.
        """
        return _PendingEmbeddingSpan(self, phase, rows)

    def record(self, phase: str, rows: int, seconds: float, status: str) -> None:
        """Append one safe diagnostic receipt without masking processing errors.

        Parameters
        ----------
        phase : str
            Stable measured operation name.
        rows : int
            Logical row count.
        seconds : float
            Measured wall-clock duration.
        status : str
            Completion or original exception type.

        Returns
        -------
        None
            Writes a receipt or warns and disables unavailable profiling.
        """

        if self.path is not None:
            rss: float | None = None
            try:
                import resource

                rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
                if sys.platform == "darwin":
                    rss /= 1024
            except ImportError:
                pass
            receipt = {
                "schema_version": 1,
                "backend": self.backend,
                "pid": os.getpid(),
                "phase": phase,
                "status": status,
                "rows": rows,
                "seconds": seconds,
                "rows_per_second": rows / seconds if seconds and rows else None,
                "lifetime_peak_rss_kib": rss,
                "rss_scope": "process lifetime high-water mark, not phase allocation",
            }
            try:
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(receipt) + "\n")
            except OSError as error:
                logging.getLogger(__name__).warning(
                    "Embedding phase journal unavailable; profiling disabled: %s",
                    error,
                )
                self.path = None


class _PendingEmbeddingSpan:
    """Measure a phase with the shared optional journal.

    Parameters
    ----------
    profile : PendingEmbeddingProfile
        Owner of the isolated diagnostic journal.
    phase : str
        Stable operation label.
    rows : int
        Logical row count.

    Returns
    -------
    None
        Creates a context which never suppresses an operation failure.
    """

    def __init__(self, profile: PendingEmbeddingProfile, phase: str, rows: int) -> None:
        """Retain the requested operation and row count.

        Parameters
        ----------
        profile : PendingEmbeddingProfile
            Journal owner.
        phase : str
            Operation label.
        rows : int
            Logical row count.

        Returns
        -------
        None
            Defers timing until context entry.
        """
        self.profile = profile
        self.phase = phase
        self.rows = rows
        self.start = 0.0

    def __enter__(self) -> None:
        """Begin measuring the operation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            Records its monotonic start time.
        """
        self.start = perf_counter()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Retain timing and exception type without suppressing interruption.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Original failure type, if any.
        error : BaseException | None
            Original exception, never serialized.
        traceback : types.TracebackType | None
            Original stack, never serialized.

        Returns
        -------
        None
            Propagates the measured operation's original failure.
        """
        self.profile.record(
            self.phase,
            self.rows,
            perf_counter() - self.start,
            "completed" if exc_type is None else exc_type.__name__,
        )
