"""Semgrep fixture for hand-written plugin configuration schemas."""

from __future__ import annotations


class ManualSchemaEmbeddingEngine:
    """Plugin-shaped class intentionally returning a manual schema dict."""

    name = "manual-schema"
    version = "1"

    def configuration_json_schema(self) -> dict[str, object]:
        """Return a deliberately hand-written schema."""
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {"enabled": {"type": "boolean"}},
        }

    def provision(self, config: dict[str, object], *, quiet: bool = False) -> None:
        """Provision the fake engine."""
        del config, quiet
