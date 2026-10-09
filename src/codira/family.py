"""Versioned local family descriptors referencing registered workspaces.

Parameters
----------
None

Returns
-------
None
    Domain values and strict descriptor loading without index ownership.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.workspace import WorkspaceDefinition, WorkspaceError
from codira.workspace_registry import WorkspaceRegistry

if TYPE_CHECKING:
    from codira.workspace import ResolvedWorkspace


class FamilyError(ValueError):
    """Report invalid family configuration or incomplete family queries.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Exception carrying an operator-facing message.
    """


@dataclass(frozen=True, order=True)
class FamilyMember:
    """Reference one registered workspace with an optional descriptive role.

    Parameters
    ----------
    workspace : str
        Registered workspace identity, also the unique family member identity.
    role : str
        Descriptive role without ranking weight.

    Returns
    -------
    None
        Immutable membership value.
    """

    workspace: str
    role: str = ""


@dataclass(frozen=True, order=True)
class FamilyEndpoint:
    """Select exactly one persisted symbol by member and source location.

    Parameters
    ----------
    workspace : str
        Declared family member name.
    name : str
        Exact indexed symbol name.
    file : str
        Repository-relative source path.
    lineno : int
        One-based definition line.

    Returns
    -------
    None
        Immutable endpoint selector.
    """

    workspace: str
    name: str
    file: str
    lineno: int


@dataclass(frozen=True, order=True)
class FamilyLink:
    """Declare a directed cross-repository reference without inferred facts.

    Parameters
    ----------
    source : FamilyEndpoint
        Source definition selector.
    target : FamilyEndpoint
        Target definition selector.

    Returns
    -------
    None
        Immutable operator-declared link.
    """

    source: FamilyEndpoint
    target: FamilyEndpoint


@dataclass(frozen=True)
class BoundFamilyMember:
    """Pin workspace routing or its startup resolution failure.

    Parameters
    ----------
    member : FamilyMember
        Declared membership.
    workspace : ResolvedWorkspace | None
        Startup-resolved immutable routing, when available.
    descriptor_sha256 : str
        Workspace descriptor digest at startup.
    error : str | None
        Resolution failure preserved for strict or partial queries.

    Returns
    -------
    None
        Immutable routing binding.
    """

    member: FamilyMember
    workspace: ResolvedWorkspace | None
    descriptor_sha256: str = ""
    error: str | None = None


@dataclass(frozen=True)
class FamilyDefinition:
    """Describe one startup-pinned local family.

    Parameters
    ----------
    name : str
        Stable family name.
    members : tuple[BoundFamilyMember, ...]
        Canonically ordered workspace bindings.
    links : tuple[FamilyLink, ...]
        Explicit cross-repository reference declarations.
    descriptor_sha256 : str
        Exact manifest digest, bound into cursors and identities.

    Returns
    -------
    None
        Immutable family contract.
    """

    name: str
    members: tuple[BoundFamilyMember, ...]
    links: tuple[FamilyLink, ...]
    descriptor_sha256: str


def _table(value: object, keys: set[str]) -> dict[str, object]:
    """Reject non-tables and unknown descriptor fields.

    Parameters
    ----------
    value : object
        Parsed TOML value.
    keys : set[str]
        Accepted keys for this table.

    Returns
    -------
    dict[str, object]
        Strictly shaped table.

    Raises
    ------
    FamilyError
        If the table shape is invalid.
    """
    if not isinstance(value, dict) or set(value) - keys:
        message = f"Invalid family table; accepted fields: {sorted(keys)}"
        raise FamilyError(message)
    return cast("dict[str, object]", value)


def _text(value: object) -> str:
    """Require a nonempty text field.

    Parameters
    ----------
    value : object
        Parsed descriptor field.

    Returns
    -------
    str
        Validated text.

    Raises
    ------
    FamilyError
        If text is absent or empty.
    """
    if not isinstance(value, str) or not value.strip():
        message = "Family fields must contain nonempty strings"
        raise FamilyError(message)
    return value


def _endpoint(value: object, members: set[str]) -> FamilyEndpoint:
    """Validate a location-qualified declared reference endpoint.

    Parameters
    ----------
    value : object
        Parsed endpoint table.
    members : set[str]
        Declared workspace names.

    Returns
    -------
    FamilyEndpoint
        Valid endpoint selector.

    Raises
    ------
    FamilyError
        If membership, path containment, or line number is invalid.
    """
    table = _table(value, {"workspace", "name", "file", "lineno"})
    workspace = _text(table.get("workspace"))
    name = _text(table.get("name"))
    if name in {".", ".."}:
        message = "Family identity cannot be a directory traversal component"
        raise FamilyError(message)
    file = _text(table.get("file"))
    lineno = table.get("lineno")
    if (
        workspace not in members
        or Path(file).is_absolute()
        or ".." in Path(file).parts
        or "\\" in file
        or not isinstance(lineno, int)
        or isinstance(lineno, bool)
        or lineno < 1
    ):
        message = "Family link requires a declared member and a safe source location"
        raise FamilyError(message)
    return FamilyEndpoint(workspace, name, Path(file).as_posix(), lineno)


def load_family(
    path: Path, *, registry: WorkspaceRegistry | None = None
) -> FamilyDefinition:
    """Load a strict v1 TOML family and pin registered workspace routing.

    Parameters
    ----------
    path : pathlib.Path
        Family manifest selected by the operator at startup.
    registry : WorkspaceRegistry | None, optional
        Injected registry; defaults to the user's workspace registry.

    Returns
    -------
    FamilyDefinition
        Validated family with individual unavailable-member failures retained.

    Raises
    ------
    FamilyError
        If descriptor syntax, fields, names, or links are invalid.
    """
    try:
        content = path.read_bytes()
        table = _table(
            tomllib.loads(content.decode("utf-8")),
            {"schema_version", "name", "members", "links"},
        )
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        message = f"Cannot read family descriptor: {error}"
        raise FamilyError(message) from error
    if type(table.get("schema_version")) is not int or table["schema_version"] != 1:
        message = "Unsupported family schema_version; expected 1"
        raise FamilyError(message)
    name = _text(table.get("name"))
    WorkspaceDefinition(name, Path(), Path())
    raw_members = table.get("members")
    raw_links = table.get("links", [])
    if (
        not isinstance(raw_members, list)
        or not raw_members
        or not isinstance(raw_links, list)
    ):
        message = "Family requires a nonempty members array and a links array"
        raise FamilyError(message)
    members: list[FamilyMember] = []
    for raw in raw_members:
        item = _table(raw, {"workspace", "role"})
        workspace = _text(item.get("workspace"))
        if workspace in {".", ".."}:
            message = (
                "Family workspace identity cannot be a directory traversal component"
            )
            raise FamilyError(message)
        WorkspaceDefinition(workspace, Path(), Path())
        role = item.get("role", "")
        if not isinstance(role, str):
            message = "Family member role must be a string"
            raise FamilyError(message)
        members.append(FamilyMember(workspace, role))
    names = {member.workspace for member in members}
    if len(names) != len(members):
        message = "Duplicate family workspace identity"
        raise FamilyError(message)
    links: list[FamilyLink] = []
    for raw in raw_links:
        item = _table(raw, {"source", "target"})
        link = FamilyLink(
            _endpoint(item.get("source"), names), _endpoint(item.get("target"), names)
        )
        if link.source.workspace == link.target.workspace or link in links:
            message = "Family links must be unique cross-repository references"
            raise FamilyError(message)
        links.append(link)
    selected_registry = registry or WorkspaceRegistry.default()
    bound: list[BoundFamilyMember] = []
    repository_roots: set[Path] = set()
    index_roots: set[Path] = set()
    for member in sorted(members):
        try:
            resolved = selected_registry.validate(member.workspace)
            index_root = (resolved.state_root / ".codira").resolve(strict=False)
            if (
                resolved.repository_root in repository_roots
                or index_root in index_roots
            ):
                message = (
                    "Family members must have distinct repository and index-state roots"
                )
                raise FamilyError(message)
            if resolved.name != member.workspace:
                message = "Family workspace descriptor identity does not match its registration"
                raise FamilyError(message)
            repository_roots.add(resolved.repository_root)
            index_roots.add(index_root)
            digest = hashlib.sha256(resolved.descriptor_path.read_bytes()).hexdigest()
            bound.append(BoundFamilyMember(member, resolved, digest))
        except (WorkspaceError, OSError) as error:
            bound.append(BoundFamilyMember(member, None, error=str(error)))
    return FamilyDefinition(
        name, tuple(bound), tuple(sorted(links)), hashlib.sha256(content).hexdigest()
    )
