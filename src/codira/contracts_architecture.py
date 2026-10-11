"""Optional bulk architecture reads at the structural backend boundary.

Parameters
----------
None

Returns
-------
None
    Backends expose resolved graph facts without unused per-symbol metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import BackendQueryConnection
    from codira.types import SymbolRow


ArchitectureRelationRow = tuple[
    str, str, str | None, str | None, str | None, str | None, int
]


@dataclass(frozen=True)
class BackendArchitectureSnapshot:
    """Describe resolved facts required for architecture aggregation.

    Parameters
    ----------
    symbols : tuple of SymbolRow
        Ordered inventory, deduplicated by module and logical symbol name.
    imports : tuple of tuple
        Module, import name, kind and defining line.
    calls, references : tuple of tuple
        Resolved outgoing call and callable-reference facts.

    Returns
    -------
    None
        Immutable logical data with no driver or physical-schema dependency.
    """

    symbols: tuple[SymbolRow, ...]
    imports: tuple[tuple[str, str, str, int], ...]
    calls: tuple[ArchitectureRelationRow, ...]
    references: tuple[ArchitectureRelationRow, ...]


@runtime_checkable
class BulkArchitectureBackend(Protocol):
    """Optionally load architecture facts with a bounded number of queries.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Existing backends may retain the shared-session legacy query fallback.
    """

    def architecture_snapshot(
        self, root: Path, *, conn: BackendQueryConnection
    ) -> BackendArchitectureSnapshot:
        """Read architecture inventory and resolved relations from one session.

        Parameters
        ----------
        root : pathlib.Path
            Indexed repository root.
        conn : BackendQueryConnection
            Caller-owned read connection, which must remain open.

        Returns
        -------
        BackendArchitectureSnapshot
            Deterministically ordered architecture facts without graph metrics.
        """
        ...
