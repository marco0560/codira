"""Versioned workspace descriptor and resolution contracts.

Responsibilities
----------------
- Represent one persisted workspace definition without registry ownership.
- Serialize and parse deterministic versioned TOML descriptors.
- Resolve descriptor-relative paths into validated canonical workspace paths.

Architectural role
------------------
This module belongs to the **workspace domain layer**. Registry, CLI, MCP, and
service code consume these contracts in later slices.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import tomlkit

if TYPE_CHECKING:
    from collections.abc import Mapping

WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_DESCRIPTOR_FILENAME = "workspace.toml"
_WORKSPACE_NAME_RE = re.compile(r"^[^/\\\x00]+$")
_WORKSPACE_KEYS = frozenset(
    {"schema_version", "name", "repository_root", "state_root", "config_file"}
)


class WorkspaceError(ValueError):
    """Stable operator-facing workspace descriptor error.

    Parameters
    ----------
    message : str
        Human-readable descriptor or resolution failure.
    """


@dataclass(frozen=True)
class WorkspaceDefinition:
    """
    Persisted, possibly descriptor-relative workspace fields.

    Parameters
    ----------
    name : str
        Stable workspace identity reserved for future family references.
    repository_root : pathlib.Path
        Repository root path, interpreted relative to the descriptor when not
        absolute.
    state_root : pathlib.Path
        State root path, interpreted relative to the descriptor when not
        absolute.
    config_file : pathlib.Path | None
        Optional configuration file interpreted relative to the descriptor.
    schema_version : int
        Workspace descriptor schema version.
    """

    name: str
    repository_root: Path
    state_root: Path
    config_file: Path | None = None
    schema_version: int = WORKSPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        """
        Validate version, identity, and declared path values.

        Parameters
        ----------
        None

        Returns
        -------
        None
            The frozen descriptor fields are accepted or an error is raised.

        Raises
        ------
        WorkspaceError
            If a field is unsupported, empty, or unsafe as a workspace name.
        """
        if self.schema_version != WORKSPACE_SCHEMA_VERSION:
            msg = (
                f"Unsupported workspace schema_version {self.schema_version}; "
                f"expected {WORKSPACE_SCHEMA_VERSION}."
            )
            raise WorkspaceError(msg)
        if not self.name.strip() or not _WORKSPACE_NAME_RE.fullmatch(self.name):
            msg = "Workspace name must be non-empty and contain no path separators."
            raise WorkspaceError(msg)
        for field_name, value in (
            ("repository_root", self.repository_root),
            ("state_root", self.state_root),
        ):
            if not str(value):
                msg = f"Workspace {field_name} must be non-empty."
                raise WorkspaceError(msg)

    def to_toml(self) -> str:
        """
        Render this workspace definition as deterministic TOML.

        Parameters
        ----------
        None

        Returns
        -------
        str
            Versioned TOML descriptor content ending with one newline.
        """
        document = tomlkit.document()
        document["schema_version"] = self.schema_version
        document["name"] = self.name
        document["repository_root"] = str(self.repository_root)
        document["state_root"] = str(self.state_root)
        if self.config_file is not None:
            document["config_file"] = str(self.config_file)
        return tomlkit.dumps(document)

    @classmethod
    def from_toml(cls, content: str) -> WorkspaceDefinition:
        """
        Parse and validate one workspace descriptor document.

        Parameters
        ----------
        content : str
            TOML document content.

        Returns
        -------
        WorkspaceDefinition
            Parsed versioned workspace definition.

        Raises
        ------
        WorkspaceError
            If TOML or workspace fields are invalid.
        """
        try:
            parsed = tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            msg = f"Invalid workspace TOML: {exc}"
            raise WorkspaceError(msg) from exc
        return _workspace_definition_from_mapping(parsed)


@dataclass(frozen=True)
class ResolvedWorkspace:
    """
    One validated workspace with canonical absolute routing paths.

    Parameters
    ----------
    name : str
        Stable workspace identity.
    descriptor_path : pathlib.Path
        Canonical source descriptor file.
    repository_root : pathlib.Path
        Canonical existing target repository root.
    state_root : pathlib.Path
        Canonical workspace state root, which may not yet exist.
    config_file : pathlib.Path | None
        Canonical optional existing configuration file.
    """

    name: str
    descriptor_path: Path
    repository_root: Path
    state_root: Path
    config_file: Path | None = None


def _workspace_definition_from_mapping(
    value: Mapping[str, object],
) -> WorkspaceDefinition:
    """
    Convert parsed TOML mapping data into a workspace definition.

    Parameters
    ----------
    value : collections.abc.Mapping[str, object]
        Parsed top-level TOML mapping.

    Returns
    -------
    WorkspaceDefinition
        Validated workspace value object.

    Raises
    ------
    WorkspaceError
        If keys or values do not match the descriptor contract.
    """
    unknown = sorted(set(value) - _WORKSPACE_KEYS)
    if unknown:
        msg = f"Unknown workspace descriptor key: {unknown[0]}."
        raise WorkspaceError(msg)
    schema_version = value.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        msg = "Workspace schema_version must be an integer."
        raise WorkspaceError(msg)
    name = value.get("name")
    if not isinstance(name, str):
        msg = "Workspace name must be a string."
        raise WorkspaceError(msg)
    repository_root = value.get("repository_root")
    if not isinstance(repository_root, str):
        msg = "Workspace repository_root must be a string."
        raise WorkspaceError(msg)
    state_root = value.get("state_root")
    if not isinstance(state_root, str):
        msg = "Workspace state_root must be a string."
        raise WorkspaceError(msg)
    config_file = value.get("config_file")
    if config_file is not None and not isinstance(config_file, str):
        msg = "Workspace config_file must be a string when provided."
        raise WorkspaceError(msg)
    return WorkspaceDefinition(
        name=name,
        repository_root=Path(repository_root),
        state_root=Path(state_root),
        config_file=Path(config_file) if config_file is not None else None,
        schema_version=schema_version,
    )


def load_workspace_definition(descriptor_path: Path) -> WorkspaceDefinition:
    """
    Read one workspace descriptor without resolving its declared paths.

    Parameters
    ----------
    descriptor_path : pathlib.Path
        Workspace TOML descriptor to read.

    Returns
    -------
    WorkspaceDefinition
        Parsed and schema-validated descriptor fields.

    Raises
    ------
    WorkspaceError
        If the descriptor is missing, unreadable, or invalid.
    """
    try:
        return WorkspaceDefinition.from_toml(
            descriptor_path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        msg = f"Cannot read workspace descriptor {descriptor_path}: {exc}"
        raise WorkspaceError(msg) from exc


def _resolve_descriptor_relative_path(value: Path, descriptor_dir: Path) -> Path:
    """
    Resolve one descriptor path against its descriptor directory.

    Parameters
    ----------
    value : pathlib.Path
        Declared absolute or descriptor-relative path.
    descriptor_dir : pathlib.Path
        Canonical directory containing the descriptor.

    Returns
    -------
    pathlib.Path
        Canonical absolute path, resolving extant symlinks and parents.
    """
    candidate = value.expanduser()
    if not candidate.is_absolute():
        candidate = descriptor_dir / candidate
    return candidate.resolve(strict=False)


def resolve_workspace(
    definition: WorkspaceDefinition,
    *,
    descriptor_path: Path,
) -> ResolvedWorkspace:
    """
    Resolve and validate one descriptor against the local filesystem.

    Parameters
    ----------
    definition : WorkspaceDefinition
        Parsed descriptor fields to resolve.
    descriptor_path : pathlib.Path
        Source descriptor location used for relative-path resolution.

    Returns
    -------
    ResolvedWorkspace
        Canonical validated workspace identity and routing paths.

    Raises
    ------
    WorkspaceError
        If a required root is missing, has the wrong type, or state would
        contain the descriptor directory.
    """
    canonical_descriptor = descriptor_path.expanduser().resolve(strict=False)
    descriptor_dir = canonical_descriptor.parent
    repository_root = _resolve_descriptor_relative_path(
        definition.repository_root,
        descriptor_dir,
    )
    state_root = _resolve_descriptor_relative_path(
        definition.state_root, descriptor_dir
    )
    config_file = (
        _resolve_descriptor_relative_path(definition.config_file, descriptor_dir)
        if definition.config_file is not None
        else None
    )

    if not repository_root.exists():
        msg = f"Workspace repository root does not exist: {repository_root}"
        raise WorkspaceError(msg)
    if not repository_root.is_dir():
        msg = f"Workspace repository root is not a directory: {repository_root}"
        raise WorkspaceError(msg)
    if state_root.exists() and not state_root.is_dir():
        msg = f"Workspace state root is not a directory: {state_root}"
        raise WorkspaceError(msg)
    if descriptor_dir.is_relative_to(state_root):
        msg = "Workspace state root must not contain its descriptor directory."
        raise WorkspaceError(msg)
    if config_file is not None:
        if not config_file.exists():
            msg = f"Workspace config file does not exist: {config_file}"
            raise WorkspaceError(msg)
        if not config_file.is_file():
            msg = f"Workspace config path is not a file: {config_file}"
            raise WorkspaceError(msg)

    return ResolvedWorkspace(
        name=definition.name,
        descriptor_path=canonical_descriptor,
        repository_root=repository_root,
        state_root=state_root,
        config_file=config_file,
    )
