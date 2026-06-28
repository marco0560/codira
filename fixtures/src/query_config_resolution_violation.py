"""Fixture that violates query hot-path config resolution guardrails."""

from pathlib import Path

from codira.config import load_effective_config


def query_hot_path(root: Path) -> object:
    """Load config directly from a query hot path."""

    return load_effective_config(root=root)
