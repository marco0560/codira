"""Verify operator resource budgets on native DuckDB connections.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

import duckdb
import pytest
from codira_backend_duckdb import DuckDBIndexBackend


def test_resource_settings_reopen_cached_connections(tmp_path: Path) -> None:
    """Apply budgets to initialization and reopen after configuration changes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned disposable repository root.

    Returns
    -------
    None
        Native settings and replacement connections are verified.
    """
    backend = DuckDBIndexBackend()
    backend.configure({"memory_limit": "1 GiB", "threads": 2})
    backend.initialize(tmp_path)
    conn = backend.open_connection(tmp_path)
    assert conn.execute("SELECT current_setting('threads')").fetchall()[0][0] == 2
    assert (
        conn.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
        == "1.0 GiB"
    )
    assert backend.open_connection(tmp_path) is conn
    backend.configure({"memory_limit": "2 GiB", "threads": 1})
    replacement = backend.open_connection(tmp_path)
    assert replacement is not conn
    assert (
        replacement.execute("SELECT current_setting('threads')").fetchall()[0][0] == 1
    )
    assert (
        replacement.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
        == "2.0 GiB"
    )
    backend.configure({})
    default = backend.open_connection(tmp_path)
    default_threads = default.execute("SELECT current_setting('threads')").fetchall()[
        0
    ][0]
    assert isinstance(default_threads, int) and default_threads > 0
    assert (
        default.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
        != "2.0 GiB"
    )
    backend.close()


@pytest.mark.parametrize(
    "options",
    [
        {"threads": 0},
        {"threads": True},
        {"threads": "2"},
        {"memory_limit": " "},
        {"memory_limit": 2},
    ],
)
def test_invalid_resource_types_preserve_configuration(
    options: dict[str, object],
) -> None:
    """Reject invalid resource types without changing prior settings.

    Parameters
    ----------
    options : dict[str, object]
        Invalid explicit plugin configuration.

    Returns
    -------
    None
        Invalid configuration fails atomically.
    """
    backend = DuckDBIndexBackend()
    backend.configure({"threads": 2})
    with pytest.raises(ValueError):
        backend.configure(options)


def test_invalid_native_budget_does_not_cache_connection(tmp_path: Path) -> None:
    """Retain native validation and permit recovery after an invalid budget.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned disposable repository root.

    Returns
    -------
    None
        A corrected budget can initialize the same repository successfully.
    """
    backend = DuckDBIndexBackend()
    backend.configure({"memory_limit": "invalid-unit"})
    with pytest.raises(duckdb.ParserException, match="memory|Memory|unit|number"):
        backend.initialize(tmp_path)
    backend.configure({"memory_limit": "1 GiB"})
    backend.initialize(tmp_path)
    conn = backend.open_connection(tmp_path)
    assert (
        conn.execute("SELECT current_setting('memory_limit')").fetchall()[0][0]
        == "1.0 GiB"
    )
    backend.close()
