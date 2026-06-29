"""Fixture that violates DuckDB vector-store full-index bulk guardrails."""


class DuckDBVectorStore:
    """Minimal fixture class for Semgrep rule validation."""

    def store_vectors(self, *args: object) -> None:
        """Placeholder normal vector-store path."""

    def store_vectors_for_full_index(self, request: object) -> None:
        """Incorrectly delegate full-index bulk writes to the normal path."""
        self.store_vectors(request)
