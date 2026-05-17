"""Compatibility re-export for legacy SQLite backend helper imports.

This module remains in core temporarily so callers that still import
``codira.sqlite_backend_support`` keep working.

The actual SQLite helper implementation now lives in the first-party SQLite
backend package.
"""

from __future__ import annotations

from codira_backend_sqlite import sqlite_support as _sqlite_support
from codira_backend_sqlite.sqlite_support import *  # noqa: F403

_flush_embedding_rows = _sqlite_support._flush_embedding_rows
_store_analysis = _sqlite_support._store_analysis
