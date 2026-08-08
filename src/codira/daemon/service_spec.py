"""Shared repository-scoped specification for foreground daemon services.

The specification is transport-neutral: systemd, launchd, and Windows SCM
render the same executable, fixed repository root, effective output directory,
and foreground command without accepting request-time paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ServiceSpecification:
    """Describe one identity-safe foreground daemon service.

    Parameters
    ----------
    root : pathlib.Path
        Resolved repository root fixed in the installed service command.
    output_root : pathlib.Path
        Resolved effective output directory fixed in the service command.
    kind : str
        Stable service family, either ``daemon`` or ``query-daemon``.
    command : tuple[str, ...]
        CLI command segments following fixed root/output arguments.
    """

    root: Path
    output_root: Path
    kind: str
    command: tuple[str, ...]

    @classmethod
    def indexing(
        cls, root: Path, output_root: Path | None = None
    ) -> ServiceSpecification:
        """Build the existing automatic-indexing service specification.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        output_root : pathlib.Path | None, optional
            Effective output root; ``None`` uses the repository root.

        Returns
        -------
        ServiceSpecification
            Fixed indexing-daemon command specification.
        """
        resolved_root = root.resolve()
        return cls(
            resolved_root,
            (output_root or resolved_root).resolve(),
            "daemon",
            ("daemon", "run"),
        )

    @classmethod
    def query(cls, root: Path, output_root: Path) -> ServiceSpecification:
        """Build one repository/output-scoped warm query service specification.

        Parameters
        ----------
        root : pathlib.Path
            Repository root.
        output_root : pathlib.Path
            Effective query-daemon output root.

        Returns
        -------
        ServiceSpecification
            Fixed query-daemon command specification.
        """
        return cls(
            root.resolve(),
            output_root.resolve(),
            "query-daemon",
            ("query-daemon", "run"),
        )

    @property
    def identity(self) -> str:
        """Return a stable digest unique to root, output, and service family.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Short SHA-256 identity suitable for platform service names.
        """
        material = f"{self.kind}\0{self.root}\0{self.output_root}".encode()
        return hashlib.sha256(material, usedforsecurity=False).hexdigest()[:16]
