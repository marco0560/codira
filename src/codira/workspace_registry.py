"""Atomic registry operations for named Codira workspaces."""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

from codira.platform_paths import PlatformPaths, platform_paths
from codira.workspace import (
    WORKSPACE_DESCRIPTOR_FILENAME,
    ResolvedWorkspace,
    WorkspaceDefinition,
    WorkspaceError,
    load_workspace_definition,
    resolve_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class WorkspaceRegistry:
    """Manage one descriptor-only workspace registry.

    Parameters
    ----------
    descriptor_root : pathlib.Path
        Root directory containing one directory per workspace descriptor.
    state_root : pathlib.Path
        Default root for per-workspace state when registration omits one.
    """

    descriptor_root: Path
    state_root: Path

    @classmethod
    def default(cls, *, paths: PlatformPaths | None = None) -> WorkspaceRegistry:
        """Build the current user's default workspace registry.

        Parameters
        ----------
        paths : codira.platform_paths.PlatformPaths | None, optional
            Injected platform paths for isolated callers and tests.

        Returns
        -------
        WorkspaceRegistry
            Registry rooted at Codira's user configuration and state paths.
        """
        resolved_paths = paths or platform_paths()
        return cls(
            descriptor_root=resolved_paths.workspace_config_root,
            state_root=resolved_paths.workspace_state_root,
        )

    def descriptor_path(self, name: str) -> Path:
        """Return the canonical descriptor location for one workspace name.

        Parameters
        ----------
        name : str
            Workspace identity validated by ``WorkspaceDefinition``.

        Returns
        -------
        pathlib.Path
            Descriptor path below this registry root.
        """
        return self.descriptor_root / name / WORKSPACE_DESCRIPTOR_FILENAME

    def list_definitions(self) -> tuple[WorkspaceDefinition, ...]:
        """List valid registered workspace definitions in name order.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[WorkspaceDefinition, ...]
            Valid descriptor values sorted by stable workspace name.

        Raises
        ------
        WorkspaceError
            If a registered descriptor is invalid or mismatched with its path.
        """
        if not self.descriptor_root.exists():
            return ()
        definitions: list[WorkspaceDefinition] = []
        for path in sorted(
            self.descriptor_root.glob(f"*/{WORKSPACE_DESCRIPTOR_FILENAME}")
        ):
            definition = load_workspace_definition(path)
            if definition.name != path.parent.name:
                msg = (
                    f"Workspace descriptor name {definition.name!r} does not match "
                    f"registry directory {path.parent.name!r}."
                )
                raise WorkspaceError(msg)
            definitions.append(definition)
        return tuple(sorted(definitions, key=lambda definition: definition.name))

    def show(self, name: str) -> WorkspaceDefinition:
        """Return one registered workspace definition.

        Parameters
        ----------
        name : str
            Registered workspace identity.

        Returns
        -------
        WorkspaceDefinition
            Parsed workspace definition.

        Raises
        ------
        WorkspaceError
            If the workspace is not registered or its descriptor is invalid.
        """
        path = self.descriptor_path(name)
        if not path.exists():
            msg = f"Workspace is not registered: {name}"
            raise WorkspaceError(msg)
        return load_workspace_definition(path)

    def validate(self, name: str) -> ResolvedWorkspace:
        """Resolve and validate one registered workspace.

        Parameters
        ----------
        name : str
            Registered workspace identity.

        Returns
        -------
        ResolvedWorkspace
            Canonical validated workspace routing paths.
        """
        path = self.descriptor_path(name)
        return resolve_workspace(self.show(name), descriptor_path=path)

    def add(self, definition: WorkspaceDefinition) -> tuple[WorkspaceDefinition, bool]:
        """Atomically register one workspace or confirm an equivalent registration.

        Parameters
        ----------
        definition : WorkspaceDefinition
            Definition to validate and persist.

        Returns
        -------
        tuple[WorkspaceDefinition, bool]
            Registered definition and whether the descriptor was newly created.

        Raises
        ------
        WorkspaceError
            If name or canonical repository root conflicts with a registration.
        """
        path = self.descriptor_path(definition.name)
        if path.exists():
            existing = load_workspace_definition(path)
            if existing == definition:
                return existing, False
            msg = f"Workspace name is already registered: {definition.name}"
            raise WorkspaceError(msg)
        self._reject_root_conflict(definition, excluding=())
        self._atomic_write(path, definition.to_toml())
        return definition, True

    def update(self, definition: WorkspaceDefinition) -> WorkspaceDefinition:
        """Atomically replace one existing workspace descriptor.

        Parameters
        ----------
        definition : WorkspaceDefinition
            Replacement descriptor with the existing workspace identity.

        Returns
        -------
        WorkspaceDefinition
            Persisted replacement definition.

        Raises
        ------
        WorkspaceError
            If no existing workspace exists or another root conflicts.
        """
        path = self.descriptor_path(definition.name)
        if not path.exists():
            msg = f"Workspace is not registered: {definition.name}"
            raise WorkspaceError(msg)
        self._reject_root_conflict(definition, excluding=(definition.name,))
        self._atomic_write(path, definition.to_toml())
        return definition

    def remove(self, name: str) -> WorkspaceDefinition:
        """Unregister one workspace without deleting repository or state data.

        Parameters
        ----------
        name : str
            Registered workspace identity.

        Returns
        -------
        WorkspaceDefinition
            Definition that was unregistered.

        Raises
        ------
        WorkspaceError
            If the workspace is missing or its descriptor cannot be removed.
        """
        path = self.descriptor_path(name)
        definition = self.show(name)
        try:
            path.unlink()
        except OSError as exc:
            msg = f"Cannot unregister workspace {name}: {exc}"
            raise WorkspaceError(msg) from exc
        return definition

    def with_defaults(
        self,
        *,
        name: str,
        repository_root: Path,
        state_root: Path | None = None,
        config_file: Path | None = None,
    ) -> WorkspaceDefinition:
        """Build one absolute workspace definition using registry defaults.

        Parameters
        ----------
        name : str
            Stable workspace identity.
        repository_root : pathlib.Path
            Target repository root.
        state_root : pathlib.Path | None, optional
            Explicit state root, or the per-name registry default.
        config_file : pathlib.Path | None, optional
            Optional repository configuration file.

        Returns
        -------
        WorkspaceDefinition
            Absolute path definition ready for registration.
        """
        return WorkspaceDefinition(
            name=name,
            repository_root=repository_root.expanduser().resolve(strict=False),
            state_root=(state_root or self.state_root / name)
            .expanduser()
            .resolve(strict=False),
            config_file=(
                config_file.expanduser().resolve(strict=False)
                if config_file is not None
                else None
            ),
        )

    def _reject_root_conflict(
        self,
        definition: WorkspaceDefinition,
        *,
        excluding: Iterable[str],
    ) -> None:
        """Reject an existing canonical repository-root registration conflict.

        Parameters
        ----------
        definition : WorkspaceDefinition
            Candidate definition to compare.
        excluding : collections.abc.Iterable[str]
            Workspace names ignored during an in-place update.

        Returns
        -------
        None
            The candidate root is unique or an error is raised.
        """
        excluded = frozenset(excluding)
        candidate_root = definition.repository_root.expanduser().resolve(strict=False)
        for existing in self.list_definitions():
            if existing.name in excluded:
                continue
            existing_root = existing.repository_root.expanduser().resolve(strict=False)
            if existing_root == candidate_root:
                msg = (
                    f"Repository root is already registered by workspace: "
                    f"{existing.name}"
                )
                raise WorkspaceError(msg)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Atomically publish descriptor content without partial writes.

        Parameters
        ----------
        path : pathlib.Path
            Destination descriptor path.
        content : str
            Complete TOML content to publish.

        Returns
        -------
        None
            The destination is replaced atomically when supported by the host.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            msg = f"Cannot write workspace descriptor {path}: {exc}"
            raise WorkspaceError(msg) from exc
