"""Fixture for DuckDB full-index bulk anti-pattern guardrails."""

from __future__ import annotations


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
