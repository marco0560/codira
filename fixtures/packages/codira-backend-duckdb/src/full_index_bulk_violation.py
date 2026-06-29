"""Fixture for DuckDB full-index bulk anti-pattern guardrails."""

from __future__ import annotations

from codira.schema import DDL  # type: ignore[attr-defined]


def _resolve_cached_prepared_embedding_rows() -> None:
    """
    Pretend to load cached vectors during a fresh full-index run.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The fixture intentionally violates repository Semgrep rules.
    """
    _ = DDL


def _store_analysis() -> None:
    """
    Pretend to run the legacy per-file persistence helper.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The fixture intentionally violates repository Semgrep rules.
    """


class BadDuckDBBackend:
    """Small backend fixture for Semgrep full-index matching."""

    def persist_full_index(self) -> None:
        """
        Trigger the DuckDB full-index bulk anti-pattern rule.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fixture intentionally calls the legacy per-file helper.
        """
        _store_analysis()
        _resolve_cached_prepared_embedding_rows()
