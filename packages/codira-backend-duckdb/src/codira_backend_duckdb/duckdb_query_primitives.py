"""Backend-compatible protocol and scalar helpers for DuckDB queries."""

from __future__ import annotations

from collections.abc import Sequence
import importlib
from typing import Protocol, cast

from codira.contracts import BackendQueryValue


class _BackendCompatibleCursor(Protocol):
    """Cursor surface shared by backend-compatible connection adapters."""

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement and retain the cursor result position.

        Parameters
        ----------
        statement : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            The active cursor positioned on the statement result.
        """

    def fetchone(self) -> tuple[BackendQueryValue, ...] | None:
        """
        Return the next available row from the active result set.

        Returns
        -------
        tuple[codira.contracts.BackendQueryValue, ...] | None
            Next available row, or ``None`` when the result is exhausted.
        """

    def fetchall(self) -> list[tuple[BackendQueryValue, ...]]:
        """
        Return every remaining row from the active result set.

        Returns
        -------
        list[tuple[codira.contracts.BackendQueryValue, ...]]
            Remaining rows from the active result set.
        """


class _BackendCompatibleConnectionAdapter(Protocol):
    """Connection surface shared by backend-compatible connection adapters."""

    def execute(
        self,
        statement: str,
        parameters: Sequence[object] | None = None,
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement on the active backend connection.

        Parameters
        ----------
        statement : str
            SQL statement to execute.
        parameters : collections.abc.Sequence[object] | None, optional
            Positional parameters bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like result wrapper for the executed statement.
        """

    def executemany(
        self,
        statement: str,
        parameters: Sequence[Sequence[object]],
    ) -> _BackendCompatibleCursor:
        """
        Execute one statement against multiple parameter rows.

        Parameters
        ----------
        statement : str
            SQL statement to execute repeatedly.
        parameters : collections.abc.Sequence[collections.abc.Sequence[object]]
            Parameter rows bound to ``statement``.

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like result wrapper for the most recent execution.
        """

    def cursor(self) -> _BackendCompatibleCursor:
        """
        Return a cursor-like object bound to the active connection.

        Returns
        -------
        _BackendCompatibleCursor
            Cursor-like object bound to the active backend connection.
        """

    def commit(self) -> None:
        """
        Commit pending writes on the active connection.

        Returns
        -------
        None
            Pending writes are committed in place.
        """

    def close(self) -> None:
        """
        Close the active backend connection.

        Returns
        -------
        None
            The active backend connection is closed.
        """


class _DuckDBModuleWithError(Protocol):
    """Minimal DuckDB module surface needed for error translation."""

    Error: type[BaseException]


_BackendCompatibleConnection = _BackendCompatibleConnectionAdapter


def _backend_int(value: BackendQueryValue) -> int:
    """
    Coerce one backend-compatible scalar into an integer.

    Parameters
    ----------
    value : BackendQueryValue
        Scalar value returned from one backend query row.

    Returns
    -------
    int
        Integer form of ``value``.
    """
    return int(cast("str | bytes | bytearray | int | float", value))


def _backend_float(value: BackendQueryValue) -> float:
    """
    Coerce one backend-compatible scalar into a float.

    Parameters
    ----------
    value : BackendQueryValue
        Scalar value returned from one backend query row.

    Returns
    -------
    float
        Floating-point form of ``value``.
    """
    return float(cast("str | bytes | bytearray | int | float", value))


def _backend_bytes(value: BackendQueryValue) -> bytes:
    """
    Coerce one backend-compatible scalar into raw bytes.

    Parameters
    ----------
    value : BackendQueryValue
        Scalar value returned from one backend query row.

    Returns
    -------
    bytes
        Raw byte representation of ``value``.
    """
    return bytes(cast("bytes | bytearray", value))


def _duckdb_error_type() -> type[BaseException]:
    """
    Return the active DuckDB driver error base class.

    Returns
    -------
    type[BaseException]
        Base exception type exported by the active DuckDB driver module.
    """
    module = importlib.import_module("duckdb")
    return cast("_DuckDBModuleWithError", module).Error
