# ruff: noqa: F401

import sqlite3


def bad() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")
