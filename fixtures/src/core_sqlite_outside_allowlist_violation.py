import sqlite3


def open_temp() -> sqlite3.Connection:
    return sqlite3.connect(":memory:")
