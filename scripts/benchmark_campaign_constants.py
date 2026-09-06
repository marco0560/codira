"""Shared defaults and command vocabulary for benchmark campaigns.

Responsibilities
----------------
- Define stable campaign defaults and supported benchmark subcommands.
- Keep adaptive-selection and command-planning token sets in one owner.

Architectural role
------------------
This module is dependency-light shared vocabulary for benchmark campaign tools.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ARTIFACT_ROOT = Path(".artifacts") / "benchmarks"
DEFAULT_RUNS = 5
DEFAULT_WARMUP = 1
DEFAULT_QUERY = "schema migration logic"
UTILITY_QUERY_SUBCOMMANDS = frozenset(
    {"ctx", "cov", "sym", "symlist", "emb", "calls", "audit"}
)
PATH_AWARE_SUBCOMMANDS = frozenset(
    {"index", "cov", "sym", "symlist", "emb", "calls", "refs", "audit", "ctx"}
)
ADAPTIVE_SYMBOL_SUBCOMMANDS = frozenset({"sym", "calls", "refs"})
ADAPTIVE_TEXT_SUBCOMMANDS = frozenset({"emb", "ctx"})
DISCOVERY_SYMBOL_LIMIT = 100
DISCOVERY_MAX_SYMBOL_CANDIDATES = 12
DISCOVERY_MAX_QUERY_CANDIDATES = 8
OPTION_FLAGS_WITH_VALUE = frozenset(
    {
        "--limit",
        "--prefix",
        "--module",
        "--path",
        "--output-dir",
        "--max-depth",
        "--config-file",
    }
)
MANIFEST_BENCHMARK_SUBCOMMANDS = frozenset(
    {
        "help",
        "index",
        "cov",
        "sym",
        "symlist",
        "emb",
        "calls",
        "refs",
        "audit",
        "ctx",
        "plugins",
        "caps",
    }
)


__all__ = (
    "ADAPTIVE_SYMBOL_SUBCOMMANDS",
    "ADAPTIVE_TEXT_SUBCOMMANDS",
    "DEFAULT_ARTIFACT_ROOT",
    "DEFAULT_QUERY",
    "DEFAULT_RUNS",
    "DEFAULT_WARMUP",
    "DISCOVERY_MAX_QUERY_CANDIDATES",
    "DISCOVERY_MAX_SYMBOL_CANDIDATES",
    "DISCOVERY_SYMBOL_LIMIT",
    "MANIFEST_BENCHMARK_SUBCOMMANDS",
    "OPTION_FLAGS_WITH_VALUE",
    "PATH_AWARE_SUBCOMMANDS",
    "UTILITY_QUERY_SUBCOMMANDS",
)
