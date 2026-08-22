"""Fixture that violates the MCP read-only mutation guardrail."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from codira.indexer import index_repo

if TYPE_CHECKING:
    from pathlib import Path


class _Store:
    """Minimal vector-store stand-in for the Semgrep fixture."""

    def purge_vector_sets(self) -> None:
        """Stand in for a vector-store mutation.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The fixture has no runtime behavior.
        """


def mutate_from_mcp(path: Path, store: _Store) -> None:
    """Contain forbidden operations that the Semgrep rule must detect.

    Parameters
    ----------
    path : pathlib.Path
        Fixture path passed to the prohibited filesystem operation.
    store : _Store
        Fixture vector store passed to the prohibited purge operation.

    Returns
    -------
    None
        The fixture is never executed.
    """
    index_repo(path)
    store.purge_vector_sets()
    path.write_text("mutation", encoding="utf-8")
    subprocess.run(["/usr/bin/true"], check=True)
