"""Example backend plugin for codira."""

from typing import cast

from codira_backend_sqlite import SQLiteIndexBackend

from codira.contracts import IndexBackend


class DemoBackend(SQLiteIndexBackend):
    """Minimal third-party backend that reuses SQLite storage."""

    name = "demo-backend"


def build_backend() -> IndexBackend:
    """
    Build the example backend plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.IndexBackend
        Example backend instance cast to the public plugin contract.
    """
    return cast("IndexBackend", DemoBackend())
