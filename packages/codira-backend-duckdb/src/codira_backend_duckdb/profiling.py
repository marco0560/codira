"""Opt-in DuckDB backend profiling helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from pathlib import Path
from time import perf_counter

PROFILE_SCHEMA_VERSION = "1"
PROFILE_FILENAME = "duckdb-profile.json"


@dataclass
class DuckDBProfileSpan:
    """
    Aggregate timings for one profiled DuckDB operation.

    Parameters
    ----------
    name : str
        Stable operation name.
    calls : int
        Number of completed spans for the operation.
    seconds_total : float
        Cumulative wall-clock seconds.
    seconds_max : float
        Slowest observed call for the operation.
    rows_total : int
        Optional cumulative row count attached by callers.
    payload_bytes_total : int
        Optional cumulative payload byte count attached by callers.
    """

    name: str
    calls: int = 0
    seconds_total: float = 0.0
    seconds_max: float = 0.0
    rows_total: int = 0
    payload_bytes_total: int = 0

    def add(
        self,
        *,
        seconds: float,
        rows: int = 0,
        payload_bytes: int = 0,
    ) -> None:
        """
        Add one completed measurement.

        Parameters
        ----------
        seconds : float
            Elapsed wall-clock seconds.
        rows : int, optional
            Row count associated with the measurement.
        payload_bytes : int, optional
            Approximate payload bytes associated with the measurement.

        Returns
        -------
        None
            Aggregate counters are updated in place.
        """

        self.calls += 1
        self.seconds_total += seconds
        self.seconds_max = max(self.seconds_max, seconds)
        self.rows_total += rows
        self.payload_bytes_total += payload_bytes

    def to_json(self) -> dict[str, int | float | str]:
        """
        Return the JSON-compatible aggregate representation.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, int | float | str]
            Stable JSON profile span payload.
        """

        return {
            "name": self.name,
            "calls": self.calls,
            "seconds_total": round(self.seconds_total, 9),
            "seconds_max": round(self.seconds_max, 9),
            "seconds_avg": round(self.seconds_total / self.calls, 9)
            if self.calls
            else 0.0,
            "rows_total": self.rows_total,
            "payload_bytes_total": self.payload_bytes_total,
        }


@dataclass
class DuckDBProfileRecorder:
    """
    Aggregate opt-in DuckDB backend profile spans.

    Parameters
    ----------
    enabled : bool
        Whether measurements should be collected and emitted.
    spans : dict[str, DuckDBProfileSpan]
        Aggregate spans keyed by stable operation name.
    """

    enabled: bool = False
    spans: dict[str, DuckDBProfileSpan] = field(default_factory=dict)

    @contextmanager
    def span(
        self,
        name: str,
        *,
        rows: int = 0,
        payload_bytes: int = 0,
    ) -> Iterator[None]:
        """
        Measure one operation if profiling is enabled.

        Parameters
        ----------
        name : str
            Stable operation name.
        rows : int, optional
            Row count associated with the operation.
        payload_bytes : int, optional
            Approximate payload bytes associated with the operation.

        Yields
        ------
        None
            Control returns to the measured operation.
        """

        if not self.enabled:
            yield
            return
        started_at = perf_counter()
        try:
            yield
        finally:
            self.record(
                name,
                seconds=perf_counter() - started_at,
                rows=rows,
                payload_bytes=payload_bytes,
            )

    def record(
        self,
        name: str,
        *,
        seconds: float,
        rows: int = 0,
        payload_bytes: int = 0,
    ) -> None:
        """
        Record one completed operation if profiling is enabled.

        Parameters
        ----------
        name : str
            Stable operation name.
        seconds : float
            Elapsed wall-clock seconds.
        rows : int, optional
            Row count associated with the operation.
        payload_bytes : int, optional
            Approximate payload bytes associated with the operation.

        Returns
        -------
        None
            Aggregate counters are updated when profiling is enabled.
        """

        if not self.enabled:
            return
        self.spans.setdefault(name, DuckDBProfileSpan(name=name)).add(
            seconds=seconds,
            rows=rows,
            payload_bytes=payload_bytes,
        )

    def to_json(
        self,
        *,
        backend_name: str,
        backend_version: str,
    ) -> dict[str, object]:
        """
        Return the stable JSON profile payload.

        Parameters
        ----------
        backend_name : str
            Backend plugin name.
        backend_version : str
            Backend plugin version.

        Returns
        -------
        dict[str, object]
            JSON-serializable profile document.
        """

        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "backend": {
                "name": backend_name,
                "version": backend_version,
            },
            "spans": [
                self.spans[name].to_json()
                for name in sorted(
                    self.spans, key=lambda item: (-self.spans[item].seconds_total, item)
                )
            ],
        }

    def write(
        self,
        path: Path,
        *,
        backend_name: str,
        backend_version: str,
    ) -> None:
        """
        Write the profile JSON document when profiling is enabled.

        Parameters
        ----------
        path : pathlib.Path
            Destination JSON path.
        backend_name : str
            Backend plugin name.
        backend_version : str
            Backend plugin version.

        Returns
        -------
        None
            The profile is written atomically enough for local benchmark use.
        """

        if not self.enabled:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_json(
            backend_name=backend_name,
            backend_version=backend_version,
        )
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def duckdb_profile_path(codira_dir: Path) -> Path:
    """
    Return the profile path below one `.codira` directory.

    Parameters
    ----------
    codira_dir : pathlib.Path
        Repository-local Codira state directory.

    Returns
    -------
    pathlib.Path
        Destination path for DuckDB backend profiling output.
    """

    return codira_dir / PROFILE_FILENAME


def classify_sql_statement(query: str) -> str:
    """
    Return a compact stable profile label for one DuckDB SQL statement.

    Parameters
    ----------
    query : str
        SQL statement text.

    Returns
    -------
    str
        Stable profile label suitable for aggregate reporting.
    """

    normalized = " ".join(query.strip().split()).lower()
    if not normalized:
        return "sql.empty"
    if "read_csv(" in normalized:
        return "sql.read_csv"
    if normalized.startswith("insert into "):
        return f"sql.insert.{_statement_table_name(normalized, 'insert into ')}"
    if normalized.startswith("insert or replace into "):
        return f"sql.insert_or_replace.{_statement_table_name(normalized, 'insert or replace into ')}"
    if normalized.startswith("delete from "):
        return f"sql.delete.{_statement_table_name(normalized, 'delete from ')}"
    if normalized.startswith("create index "):
        return "sql.create_index"
    if normalized.startswith("create unique index "):
        return "sql.create_index"
    if normalized.startswith("drop index "):
        return "sql.drop_index"
    if normalized.startswith("create table "):
        return "sql.create_table"
    if normalized.startswith("drop table "):
        return "sql.drop_table"
    if normalized.startswith("select "):
        return "sql.select"
    if normalized.startswith("begin"):
        return "sql.begin"
    if normalized.startswith("commit"):
        return "sql.commit"
    if normalized.startswith("rollback"):
        return "sql.rollback"
    return f"sql.{normalized.split(' ', 1)[0]}"


def _statement_table_name(normalized: str, prefix: str) -> str:
    """
    Return the first table token after a SQL statement prefix.

    Parameters
    ----------
    normalized : str
        Lowercase whitespace-normalized SQL statement.
    prefix : str
        Statement prefix before the table name.

    Returns
    -------
    str
        Sanitized table label.
    """

    remainder = normalized[len(prefix) :].lstrip()
    token = remainder.split("(", 1)[0].split(" ", 1)[0].strip()
    return token.replace('"', "").replace("'", "") or "unknown"
