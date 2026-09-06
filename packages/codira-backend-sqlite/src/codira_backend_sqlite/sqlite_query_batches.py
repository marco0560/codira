"""SQLite variable-limit-safe SQL binding helpers."""

from __future__ import annotations


_SQLITE_VARIABLE_BATCH_SIZE = 900


def _placeholders(values: list[int]) -> str:
    """
    Build a positional placeholder string for SQL ``IN`` clauses.

    Parameters
    ----------
    values : list[int]
        Integer values that will populate the clause.

    Returns
    -------
    str
        Comma-separated ``?`` placeholders sized to ``values``.
    """
    return ",".join("?" for _ in values)


def _path_batches(paths: list[str]) -> list[list[str]]:
    """
    Split path values into SQLite variable-limit-safe batches.

    Parameters
    ----------
    paths : list[str]
        Path values to bind into SQL statements.

    Returns
    -------
    list[list[str]]
        Consecutive non-empty batches sized below SQLite's conservative limit.
    """
    return [
        paths[index : index + _SQLITE_VARIABLE_BATCH_SIZE]
        for index in range(0, len(paths), _SQLITE_VARIABLE_BATCH_SIZE)
    ]
