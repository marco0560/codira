"""Read-only federation over independent workspace indexes.

Parameters
----------
None

Returns
-------
None
    Generation-bound family retrieval and explicit reference validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal, cast

from codira.config import (
    effective_config_cache,
    load_effective_config,
    override_repo_config_path,
)
from codira.contracts import BackendError
from codira.family import (
    BoundFamilyMember,
    FamilyDefinition,
    FamilyEndpoint,
    FamilyError,
)
from codira.git import read_head_commit
from codira.index_coverage import analysis_fingerprint, index_coverage
from codira.index_generation import IndexGenerationStore
from codira.mcp.adapter import MCPAdapter
from codira.registry import (
    active_index_backend,
    active_language_analyzers,
    active_plugin_instance_cache,
)
from codira.runtime_identity import runtime_identity
from codira.scanner import file_metadata, iter_project_files
from codira.storage import override_storage_root

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

FamilyOperation = Literal["context", "symbol", "references"]


def _digest(value: object) -> str:
    """Hash a deterministic JSON value.

    Parameters
    ----------
    value : object
        JSON-compatible binding data.

    Returns
    -------
    str
        SHA-256 digest.
    """
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _encode(prefix: str, value: object) -> str:
    """Encode opaque JSON routing data without raw repository paths.

    Parameters
    ----------
    prefix : str
        Identity type marker.
    value : object
        JSON-compatible payload.

    Returns
    -------
    str
        Opaque identity or cursor.
    """
    return (
        prefix
        + base64.urlsafe_b64encode(json.dumps(value, sort_keys=True).encode()).decode()
    )


def _decode(prefix: str, value: str) -> dict[str, object]:
    """Decode a typed identity or continuation cursor.

    Parameters
    ----------
    prefix : str
        Required type marker.
    value : str
        Encoded value supplied by a caller.

    Returns
    -------
    dict[str, object]
        Decoded object.

    Raises
    ------
    FamilyError
        If the marker, encoding, or payload is invalid.
    """
    message = "Invalid family identity or continuation cursor"
    if not value.startswith(prefix):
        raise FamilyError(message)
    try:
        decoded = json.loads(
            base64.b64decode(value[len(prefix) :], altchars=b"-_", validate=True)
        )
    except (ValueError, UnicodeError) as error:
        raise FamilyError(message) from error
    if not isinstance(decoded, dict):
        raise FamilyError(message)
    return cast("dict[str, object]", decoded)


@contextmanager
def member_scope(member: BoundFamilyMember) -> Iterator[MCPAdapter]:
    """Enter isolated config, plugin, and storage scopes for a pinned member.

    Parameters
    ----------
    member : BoundFamilyMember
        Startup-resolved workspace binding.

    Yields
    ------
    MCPAdapter
        Adapter scoped to this member's configuration, plugins, and storage.

    Raises
    ------
    FamilyError
        If member routing was unavailable at startup.
    """
    workspace = member.workspace
    if workspace is None:
        message = member.error or "Family workspace is unavailable"
        raise FamilyError(message)
    with (
        override_storage_root(workspace.repository_root, workspace.state_root),
        override_repo_config_path(workspace.config_file),
        effective_config_cache(),
        active_plugin_instance_cache(),
    ):
        backend = active_index_backend(root=workspace.repository_root)
        try:
            yield MCPAdapter(workspace.repository_root)
        finally:
            close = cast("Callable[[], None] | None", getattr(backend, "close", None))
            if close is not None:
                close()


def member_state(member: BoundFamilyMember) -> dict[str, object]:
    """Verify index readiness, runtime compatibility, and current source hashes.

    Parameters
    ----------
    member : BoundFamilyMember
        Workspace binding to check within its member scope.

    Returns
    -------
    dict[str, object]
        Safe generation and configuration binding without absolute paths.

    Raises
    ------
    FamilyError
        If the index is unavailable, stale, or being modified.
    """
    workspace = member.workspace
    if workspace is None:
        message = member.error or "Family workspace is unavailable"
        raise FamilyError(message)
    root = workspace.repository_root
    record = IndexGenerationStore(root).read()
    if record is None or record.state != "ready" or not record.indexed_file_count:
        message = (
            "Member index is unavailable, updating, failed, or empty; run family index"
        )
        raise FamilyError(message)
    backend = active_index_backend(root=root)
    analyzers = active_language_analyzers(root=root)
    inventory = [
        {"name": str(item.name), "version": str(item.version)}
        for item in sorted(analyzers, key=lambda item: str(item.name))
    ]
    stored_inventory = [
        {"name": item.get("name"), "version": item.get("version")}
        for item in record.analyzer_inventory or []
    ]
    stored_inventory.sort(key=lambda item: str(item["name"]))
    if (
        record.backend_name != str(backend.name)
        or record.backend_version != str(backend.version)
        or stored_inventory != inventory
        or record.git_commit != read_head_commit(root)
    ):
        message = (
            "Member index is stale: repository revision or plugin inventory changed"
        )
        raise FamilyError(message)
    if record.partial and record.analysis_fingerprint != analysis_fingerprint(root):
        message = "Member failure configuration changed; run family index"
        raise FamilyError(message)
    hashes = backend.load_existing_file_hashes(root)
    hashes.update(
        {
            str(root / failure["path"]): failure["sha256"]
            for failure in record.failed_files or []
        }
    )
    current = {
        str(path): str(file_metadata(path)["hash"])
        for path in iter_project_files(root, analyzers=analyzers)
    }
    if hashes != current:
        message = "Member index is stale: source files changed"
        raise FamilyError(message)
    return {
        "generation": record.generation,
        "index_coverage": index_coverage(root),
        "workspace_descriptor_sha256": member.descriptor_sha256,
        "routing_sha256": _digest(
            [str(root), str(workspace.state_root), str(workspace.config_file)]
        ),
        "configuration_sha256": _digest(asdict(load_effective_config(root=root))),
        "backend": [record.backend_name, record.backend_version],
        "sources_sha256": _digest(hashes),
    }


@dataclass(frozen=True)
class FamilyRuntime:
    """Serve one immutable family selected by CLI or MCP startup.

    Parameters
    ----------
    family : FamilyDefinition
        Pinned manifest and workspace routing.

    Returns
    -------
    None
        Read-only family runtime.
    """

    family: FamilyDefinition

    def _snapshot(self) -> tuple[dict[str, object], list[dict[str, str]]]:
        """Collect all member states, including members outside a query filter.

        Parameters
        ----------
        None

        Returns
        -------
        tuple[dict[str, object], list[dict[str, str]]]
            Generation/configuration vector and unavailable-member reasons.
        """
        states: dict[str, object] = {}
        errors: list[dict[str, str]] = []
        for member in self.family.members:
            try:
                with member_scope(member):
                    states[member.member.workspace] = member_state(member)
            except (BackendError, OSError, RuntimeError, ValueError) as error:
                states[member.member.workspace] = {"unavailable": str(error)}
                errors.append(
                    {"repository": member.member.workspace, "reason": str(error)}
                )
        return states, errors

    def status(self) -> dict[str, object]:
        """Inspect all members without requiring a usable family index.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Safe per-member readiness and failure information.
        """
        states, errors = self._snapshot()
        return self._envelope([], states, errors, {})

    def _qualify(
        self, member: BoundFamilyMember, item: dict[str, object]
    ) -> dict[str, object]:
        """Attach origin and wrap member identities in family scope.

        Parameters
        ----------
        member : BoundFamilyMember
            Origin workspace.
        item : dict[str, object]
            Repository-local retrieval item.

        Returns
        -------
        dict[str, object]
            Repository-qualified item with complete evidence preserved.
        """
        result = {
            **item,
            "repository": member.member.workspace,
            "role": member.member.role,
        }
        if "line" in item:
            result["lineno"] = item["line"]
        if "kind" in item:
            result["type"] = item["kind"]
        identity = item.get("identity")
        if isinstance(identity, str):
            result["identity"] = _encode(
                "family-sym:",
                {
                    "family": self.family.name,
                    "manifest": self.family.descriptor_sha256,
                    "repository": member.member.workspace,
                    "workspace_descriptor_sha256": member.descriptor_sha256,
                    "local": identity,
                },
            )
        return result

    def _collect(
        self, member: BoundFamilyMember, operation: FamilyOperation, query: str
    ) -> list[dict[str, object]]:
        """Collect complete member pages before family ranking and pagination.

        Parameters
        ----------
        member : BoundFamilyMember
            Origin workspace.
        operation : FamilyOperation
            Exact-symbol or context retrieval.
        query : str
            Query text or exact name.

        Returns
        -------
        list[dict[str, object]]
            All member candidates returned by its existing retrieval contract.
        """
        items: list[dict[str, object]] = []
        cursor: str | None = None
        with member_scope(member) as adapter:
            while True:
                response = (
                    adapter.context_for_task(query, cursor=cursor, limit=100)
                    if operation == "context"
                    else adapter.symbol(query, cursor=cursor, limit=100)
                )
                result = cast("dict[str, object]", response["result"])
                for item in cast(
                    "list[dict[str, object]]",
                    result["items" if operation == "context" else "symbols"],
                ):
                    qualified = self._qualify(member, item)
                    if operation == "context":
                        qualified["member_rank"] = len(items) + 1
                        qualified["member_ranking_score"] = item.get("ranking_score")
                        qualified["ranking_score"] = 1.0 / (60 + len(items) + 1)
                        qualified["score_kind"] = "family_reciprocal_rank"
                    items.append(qualified)
                page = cast("dict[str, object]", response["page"])
                cursor = cast("str | None", page.get("next_cursor"))
                if cursor is None:
                    break
        return items

    def _resolve_endpoint(self, endpoint: FamilyEndpoint) -> dict[str, object]:
        """Resolve an explicit endpoint to exactly one indexed definition.

        Parameters
        ----------
        endpoint : FamilyEndpoint
            Manifest selector with exact name, file, and line.

        Returns
        -------
        dict[str, object]
            Repository-qualified definition.

        Raises
        ------
        FamilyError
            If the declared endpoint is missing or ambiguous.
        """
        member = next(
            item
            for item in self.family.members
            if item.member.workspace == endpoint.workspace
        )
        matches = [
            item
            for item in self._collect(member, "symbol", endpoint.name)
            if item["file"] == endpoint.file and item["lineno"] == endpoint.lineno
        ]
        if len(matches) != 1:
            message = f"Declared family endpoint does not resolve uniquely: {endpoint.workspace}:{endpoint.file}:{endpoint.lineno}:{endpoint.name}"
            raise FamilyError(message)
        return matches[0]

    def _references(
        self,
        query: str,
        repositories: tuple[str, ...],
        direction: str,
        unavailable: set[str],
    ) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
        """Validate and select operator-declared cross-repository references.

        Parameters
        ----------
        query : str
            Exact endpoint name.
        repositories : tuple[str, ...]
            Member filter applied to the queried side of each edge.
        direction : str
            Incoming or outgoing traversal.
        unavailable : set[str]
            Members whose endpoints cannot be validated.

        Returns
        -------
        tuple[list[dict[str, object]], list[dict[str, str]]]
            Valid explicit edges and excluded-link reasons.
        """
        items: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for link in self.family.links:
            endpoint = link.source if direction == "outgoing" else link.target
            if endpoint.name != query or (
                repositories and endpoint.workspace not in repositories
            ):
                continue
            try:
                if {link.source.workspace, link.target.workspace} & unavailable:
                    message = "Declared link endpoint repository is unavailable"
                    raise FamilyError(message)
                items.append(
                    {
                        "source": self._resolve_endpoint(link.source),
                        "target": self._resolve_endpoint(link.target),
                        "provenance": "family_manifest",
                        "relation": "reference",
                        "resolved": True,
                    }
                )
            except (BackendError, OSError, RuntimeError, ValueError) as error:
                errors.append({"repository": endpoint.workspace, "reason": str(error)})
        return items, errors

    def query(  # noqa: PLR0913 - explicit transport-independent query options
        self,
        operation: FamilyOperation,
        query: str,
        *,
        repositories: tuple[str, ...] = (),
        cursor: str | None = None,
        limit: int = 10,
        allow_partial: bool = False,
        direction: str = "outgoing",
    ) -> dict[str, object]:
        """Retrieve, qualify, globally rank, and page family results.

        Parameters
        ----------
        operation : FamilyOperation
            Context, exact-symbol lookup, or declared reference traversal.
        query : str
            Nonempty query or exact symbol name.
        repositories : tuple[str, ...], optional
            Filter restricted to declared member names.
        cursor : str | None, optional
            Exact continuation returned by this family query.
        limit : int, optional
            Global page size from one to one hundred.
        allow_partial : bool, optional
            Return explicitly labeled partial results on member failures.
        direction : str, optional
            Incoming or outgoing declared references.

        Returns
        -------
        dict[str, object]
            Versioned family envelope with complete items and member provenance.

        Raises
        ------
        FamilyError
            If parameters, member readiness, links, or continuation are invalid.
        """
        names = {item.member.workspace for item in self.family.members}
        if (
            operation not in {"context", "symbol", "references"}
            or not query.strip()
            or type(limit) is not int
            or not 1 <= limit <= 100
            or direction not in {"incoming", "outgoing"}
            or set(repositories) - names
        ):
            message = "Invalid family query, page size, direction, or member filter"
            raise FamilyError(message)
        repositories = tuple(sorted(set(repositories)))
        states, errors = self._snapshot()
        selected_errors = [
            error
            for error in errors
            if not repositories or error["repository"] in repositories
        ]
        unavailable = {error["repository"] for error in errors}
        items: list[dict[str, object]] = []
        if operation == "references":
            items, link_errors = self._references(
                query, repositories, direction, unavailable
            )
            selected_errors.extend(link_errors)
        else:
            for member in self.family.members:
                name = member.member.workspace
                if name in unavailable or (repositories and name not in repositories):
                    continue
                try:
                    items.extend(self._collect(member, operation, query))
                except (BackendError, OSError, RuntimeError, ValueError) as error:
                    selected_errors.append({"repository": name, "reason": str(error)})
        partial_members = [
            name
            for name, state in states.items()
            if (not repositories or name in repositories)
            and cast("dict[str, object]", state).get("index_coverage", {})
            and cast(
                "dict[str, object]", cast("dict[str, object]", state)["index_coverage"]
            )["partial"]
        ]
        if partial_members and not allow_partial:
            message = "Family query has partial source coverage; pass allow_partial explicitly"
            raise FamilyError(message)
        if selected_errors and not allow_partial:
            message = "Family query incomplete: " + "; ".join(
                f"{item['repository']}: {item['reason']}" for item in selected_errors
            )
            raise FamilyError(message)
        after, _ = self._snapshot()
        if after != states:
            message = "Family members changed during retrieval; retry the query"
            raise FamilyError(message)
        items.sort(
            key=lambda item: (
                -float(str(item.get("ranking_score", 0))),
                str(item.get("repository", "")),
                str(item.get("file", "")),
                str(item.get("lineno", "")),
                str(item.get("name", "")),
                json.dumps(item, sort_keys=True),
            )
        )
        binding = _digest(
            {
                "manifest": self.family.descriptor_sha256,
                "family": self.family.name,
                "states": states,
                "runtime": runtime_identity(),
                "operation": operation,
                "query": query,
                "repositories": repositories,
                "limit": limit,
                "allow_partial": allow_partial,
                "direction": direction,
                "results": items,
                "errors": selected_errors,
            }
        )
        offset = 0
        if cursor is not None:
            decoded = _decode("family-ctx:", cursor)
            position = decoded.get("offset")
            if (
                decoded.get("binding") != binding
                or type(position) is not int
                or position < 0
                or position > len(items)
            ):
                message = "Family cursor does not match this query, manifest, or member generations; restart pagination"
                raise FamilyError(message)
            offset = position
        selected = items[offset : offset + limit]
        next_offset = offset + len(selected)
        page: dict[str, object] = {
            "offset": offset,
            "limit": limit,
            "total": len(items),
            "has_more": next_offset < len(items),
            "next_cursor": _encode(
                "family-ctx:", {"binding": binding, "offset": next_offset}
            )
            if next_offset < len(items)
            else None,
        }
        return self._envelope(selected, states, selected_errors, page)

    def evidence(self, identity: str, *, limit: int = 10) -> dict[str, object]:
        """Expand a family identity only within its declared startup member.

        Parameters
        ----------
        identity : str
            Family-qualified symbol identity returned by retrieval.
        limit : int, optional
            Maximum static relationship evidence items.

        Returns
        -------
        dict[str, object]
            Complete repository-qualified source evidence.

        Raises
        ------
        FamilyError
            If family scope, manifest, origin, or index readiness is invalid.
        """
        payload = _decode("family-sym:", identity)
        member = next(
            (
                item
                for item in self.family.members
                if item.member.workspace == payload.get("repository")
            ),
            None,
        )
        if (
            payload.get("family") != self.family.name
            or payload.get("manifest") != self.family.descriptor_sha256
            or member is None
            or payload.get("workspace_descriptor_sha256") != member.descriptor_sha256
            or not isinstance(payload.get("local"), str)
        ):
            message = "Symbol identity belongs to another family or member"
            raise FamilyError(message)
        with member_scope(member) as adapter:
            state = member_state(member)
            response = adapter.symbol_evidence(
                cast("str", payload["local"]), limit=limit
            )
            if member_state(member) != state:
                message = "Family member changed during evidence expansion"
                raise FamilyError(message)
        response["result"] = self._qualify(
            member, cast("dict[str, object]", response["result"])
        )
        response["provenance"] = {
            "family": self.family.name,
            "repository": member.member.workspace,
            "family_descriptor_sha256": self.family.descriptor_sha256,
            "index_coverage": state["index_coverage"],
        }
        return response

    def _envelope(
        self,
        items: list[dict[str, object]],
        states: dict[str, object],
        errors: list[dict[str, str]],
        page: dict[str, object],
    ) -> dict[str, object]:
        """Build a stable family response with explicit completeness metadata.

        Parameters
        ----------
        items : list[dict[str, object]]
            Complete selected result items.
        states : dict[str, object]
            All-member generation vector.
        errors : list[dict[str, str]]
            Excluded members or declared links and their reasons.
        page : dict[str, object]
            Global continuation metadata.

        Returns
        -------
        dict[str, object]
            Family contract envelope.
        """
        return {
            "contract_version": "1.0.0",
            "result": {
                "status": "partial"
                if errors
                or any(
                    cast(
                        "dict[str, object]",
                        cast("dict[str, object]", state).get("index_coverage", {}),
                    ).get("partial")
                    for state in states.values()
                )
                else "ok",
                "items": items,
                "excluded": errors,
            },
            "provenance": {
                "source": "codira-family",
                "family": self.family.name,
                "family_descriptor_sha256": self.family.descriptor_sha256,
                "ranking": "reciprocal_rank_k60",
            },
            "freshness": {"members": states},
            "page": page,
            "truncation": {"truncated": False, "reasons": []},
        }
