"""Shared repository-scoped specification for foreground daemon services.

The specification is transport-neutral: systemd, launchd, and Windows SCM
render the same executable, fixed repository root, effective output directory,
and foreground command without accepting request-time paths.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


class ServiceDefinitionDriftError(RuntimeError):
    """Report an installed service definition that no longer matches startup.

    Parameters
    ----------
    message : str
        Stable remediation describing the required service regeneration.
    """


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
    workspace_name : str | None
        Workspace selected before service construction, if any.
    descriptor_fingerprint : str | None
        SHA-256 digest of the workspace descriptor used at service creation.
    effective_config : collections.abc.Mapping[str, object]
        Effective configuration snapshot fixed for drift comparison.
    """

    root: Path
    output_root: Path
    kind: str
    command: tuple[str, ...]
    workspace_name: str | None = None
    descriptor_fingerprint: str | None = None
    effective_config: Mapping[str, object] | None = None

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

    @classmethod
    def workspace(  # noqa: PLR0913
        cls,
        *,
        kind: str,
        root: Path,
        output_root: Path,
        workspace_name: str,
        descriptor_fingerprint: str,
        effective_config: Mapping[str, object],
    ) -> ServiceSpecification:
        """Build one immutable workspace-scoped foreground service contract.

        Parameters
        ----------
        kind : {"daemon", "query-daemon"}
            Service family to run in the foreground.
        root : pathlib.Path
            Canonical repository root resolved from the workspace.
        output_root : pathlib.Path
            Canonical state root resolved from the workspace.
        workspace_name : str
            Stable registered workspace identity.
        descriptor_fingerprint : str
            SHA-256 digest of the descriptor consumed at startup.
        effective_config : collections.abc.Mapping[str, object]
            Effective configuration snapshot for stale-definition comparison.

        Returns
        -------
        ServiceSpecification
            Workspace-bound service command specification.

        Raises
        ------
        ValueError
            If service identity or descriptor fingerprint is invalid.
        """
        if kind not in {"daemon", "query-daemon"}:
            msg = f"Unsupported service kind: {kind}"
            raise ValueError(msg)
        if not workspace_name.strip() or len(descriptor_fingerprint) != 64:
            msg = (
                "Workspace service requires a name and SHA-256 descriptor fingerprint."
            )
            raise ValueError(msg)
        command = (kind, "run")
        return cls(
            root.resolve(),
            output_root.resolve(),
            kind,
            command,
            workspace_name=workspace_name,
            descriptor_fingerprint=descriptor_fingerprint,
            effective_config=json.loads(json.dumps(effective_config, sort_keys=True)),
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
        material = f"{self.kind}\0{self.root}\0{self.output_root}"
        if self.workspace_name is not None:
            material += (
                f"\0{self.workspace_name}\0{self.descriptor_fingerprint}"
                f"\0{self.config_fingerprint}"
            )
        encoded_material = material.encode()
        return hashlib.sha256(encoded_material, usedforsecurity=False).hexdigest()[:16]

    @property
    def config_fingerprint(self) -> str:
        """Return the deterministic effective-config fingerprint.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 digest of the canonical effective configuration snapshot.
        """
        payload = json.dumps(
            self.effective_config or {}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def definition_fingerprint(self) -> str:
        """Return the immutable installed-definition fingerprint.

        Parameters
        ----------
        None

        Returns
        -------
        str
            SHA-256 digest covering paths, command, workspace, and config.
        """
        payload = json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def definition_path(self) -> Path:
        """Return the persisted installed-definition record path.

        Parameters
        ----------
        None

        Returns
        -------
        pathlib.Path
            Service record under the fixed output root.
        """
        return self.output_root / ".codira" / "services" / f"{self.kind}.json"

    def startup_arguments(self) -> tuple[str, ...]:
        """Return fixed CLI arguments for the installed foreground service.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[str, ...]
            Workspace selector or legacy direct path/output selectors.
        """
        if self.workspace_name is not None:
            assert self.descriptor_fingerprint is not None
            return (
                "--workspace",
                self.workspace_name,
                "--workspace-fingerprint",
                self.descriptor_fingerprint,
            )
        arguments: tuple[str, ...] = ("--path", str(self.root))
        if self.kind == "query-daemon" or self.output_root != self.root:
            arguments += ("--output-dir", str(self.output_root))
        return arguments

    def to_mapping(self) -> dict[str, object]:
        """Return a JSON-compatible installed-definition payload.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Complete fixed service declaration without volatile state.
        """
        return {
            "schema_version": 1,
            "kind": self.kind,
            "root": str(self.root),
            "output_root": str(self.output_root),
            "command": list(self.command),
            "workspace": self.workspace_name,
            "descriptor_fingerprint": self.descriptor_fingerprint,
            "effective_config": self.effective_config or {},
        }

    def write_definition(self) -> None:
        """Atomically publish this service definition after explicit install.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The complete definition record replaces any prior explicit install.
        """
        self.definition_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.definition_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "fingerprint": self.definition_fingerprint,
                    "specification": self.to_mapping(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.definition_path)

    def require_current_definition(self) -> None:
        """Reject lifecycle actions when their installed definition is stale.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The persisted definition matches the current fixed specification.

        Raises
        ------
        ServiceDefinitionDriftError
            If no matching explicit installation exists.
        """
        if self.workspace_name is None:
            return
        try:
            payload = json.loads(self.definition_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            msg = "Service definition is unavailable; run install to regenerate it."
            raise ServiceDefinitionDriftError(msg) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("fingerprint") != self.definition_fingerprint
        ):
            msg = "Service definition drift detected; run install and restart it."
            raise ServiceDefinitionDriftError(msg)

    def remove_definition(self) -> None:
        """Remove only this persisted service definition record.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The record is absent after uninstall; repository data remains.
        """
        self.definition_path.unlink(missing_ok=True)
