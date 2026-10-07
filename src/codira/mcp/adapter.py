"""Adapt Codira core queries to the local read-only MCP contract.

The adapter owns a repository root selected when the server starts. MCP tool
requests never accept repository paths and delegate directly to core APIs.


Parameters
----------
None

Returns
-------
None
    Definitions are consumed by the local MCP or qualification workflow.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from codira.architecture import (
    ArchitectureModel,
    ArchitectureModule,
    build_architecture_model_from_index,
)
from codira.capabilities import build_capability_contract
from codira.config import load_effective_config
from codira.index_generation import IndexGenerationStore
from codira.indexer import (
    CoverageIssue,
    audit_repo_coverage,
    persisted_analysis_coverage_issues,
)
from codira.mcp.contract import (
    CURSOR_GUIDANCE,
    DEFAULT_OUTPUT_BUDGET,
    MAX_OUTPUT_BUDGET,
    MCP_CONTRACT_VERSION,
    build_contract_document,
)
from codira.prefix import normalize_prefix
from codira.query.context import ContextRequest, context_for
from codira.query.evidence import expand_symbol, symbol_identity
from codira.query.exact import (
    EdgeQueryRequest,
    docstring_issues,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    logical_symbol_name,
    symbol_inventory,
)
from codira.query.symbol_resolution import alias_evidence
from codira.registry import active_index_backend, active_similarity_search_profile
from codira.runtime_identity import runtime_identity
from codira.semantic.search import (
    DocumentationCandidatesRequest,
    EmbeddingCandidatesRequest,
    documentation_candidates,
    embedding_candidates,
    similarity_candidate_provenance_payload,
    similarity_query_provenance_payload,
)
from codira.storage import _read_metadata_file, get_metadata_path

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from codira.contracts import (
        BackendGraphMetric,
        BackendQueryConnection,
        BackendSymbolInventoryItem,
        SimilarityResolvedCandidate,
    )
    from codira.index_generation import IndexGeneration
    from codira.types import (
        DocstringIssueRow,
        ScoredDocumentation,
        ScoredSymbol,
        SymbolRow,
    )


_MIN_RESULT_LIMIT = 1
_MAX_RESULT_LIMIT = 100
_REPOSITORY_MAP_INVENTORY_LIMIT = 10_000
_Row = TypeVar("_Row")
_QueryResult = TypeVar("_QueryResult")


class QueryExecutor(Protocol):
    """Execute read operations against a supplied backend connection.

    Parameters
    ----------
    None
    """

    def execute(
        self,
        operation: Callable[[BackendQueryConnection], _QueryResult],
    ) -> _QueryResult:
        """Execute one connection-owning read operation.

        Parameters
        ----------
        operation : collections.abc.Callable
            Read operation receiving a backend connection.

        Returns
        -------
        object
            Result from the supplied operation.
        """
        ...


@dataclass(frozen=True)
class MCPAdapter:
    """Serve approved MCP operations for one startup-trusted repository root.

    Parameters
    ----------
    root : pathlib.Path
        Existing repository directory selected when the MCP server starts.
    query_executor : QueryExecutor | None, optional
        Warm executor for read operations. When omitted, the adapter preserves
        direct-core execution and opens connections through existing APIs.
    startup_provenance : collections.abc.Mapping[str, object] | None, optional
        Safe startup identity metadata supplied by the server binding.
    """

    root: Path
    query_executor: QueryExecutor | None = None
    startup_provenance: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        """Resolve and validate the configured repository root.

        Parameters
        ----------
        None

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the configured root is not an existing directory.
        """
        root = self.root.resolve()
        if not root.is_dir():
            msg = f"MCP repository root is not a directory: {root}"
            raise ValueError(msg)
        object.__setattr__(self, "root", root)

    def capabilities(self, *, detail: bool = False) -> dict[str, object]:
        """Return MCP and Codira capability documents from direct core APIs.

        Parameters
        ----------
        detail : bool, optional
            Include the complete analyzer and response-schema inventories.

        Returns
        -------
        dict[str, object]
            Contract envelope containing MCP and Codira capability documents.
        """
        contract = build_contract_document(root=self.root)
        core = build_capability_contract(root=self.root)
        if not detail:
            contract["tools"] = [
                {key: value for key, value in tool.items() if key != "response_schema"}
                for tool in cast("list[dict[str, object]]", contract["tools"])
            ]
            core = {key: core[key] for key in ("schema_version", "validation", "mcp")}
        return self._envelope(
            {"mcp": contract, "codira": core, "runtime": runtime_identity()}
        )

    def symbol_evidence(self, identity: str, *, limit: int = 10) -> dict[str, object]:
        """Expand one indexed identity into verified whole source evidence.

        Parameters
        ----------
        identity : str
            Generation-bound symbol identity returned by discovery.
        limit : int, optional
            Maximum complete static relationship items.

        Returns
        -------
        dict[str, object]
            Source definition, range, digest and bounded relationship evidence.
        """
        return self._envelope(
            expand_symbol(self.root, identity, limit=limit), output_budget=None
        )

    def symbol(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Look up exact symbol names through Codira's query layer.

        Parameters
        ----------
        name : str
            Exact symbol name to retrieve.
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic matches to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing normalized symbol matches.

        Raises
        ------
        ValueError
            If ``limit`` is outside the contract's supported range.
        """
        rows, page = self._page_rows(
            self._query(lambda conn: find_symbol(self.root, name, conn=conn)),
            cursor,
            limit,
            binding=f"symbol:{name}",
        )
        return self._envelope(
            {
                "symbols": [self._symbol_payload(row) for row in rows],
                **(
                    {"alias_edges": edges}
                    if (
                        edges := self._query(
                            lambda conn: alias_evidence(self.root, name, conn)
                        )
                    )
                    else {}
                ),
                **({"ambiguous": True} if int(str(page["total"])) > 1 else {}),
            },
            page=page,
            output_budget=output_budget,
        )

    def index_status(self, *, detail: bool = False) -> dict[str, object]:
        """Return persisted index metadata and current coverage diagnostics.

        Parameters
        ----------
        detail : bool, optional
            Include full metadata and individual coverage diagnostics.

        Returns
        -------
        dict[str, object]
            Contract envelope containing index metadata and coverage findings.
        """
        metadata = _read_metadata_file(get_metadata_path(self.root))
        generation = IndexGenerationStore(self.root).read()
        issues = audit_repo_coverage(self.root)
        indexed_file_count = metadata.get("indexed_file_count")
        empty_index = indexed_file_count == "0"
        if empty_index:
            issues.append(
                CoverageIssue(
                    path=".",
                    directory=".",
                    suffix="",
                    reason=(
                        "index contains zero files; verify that repository files "
                        "are tracked or staged"
                    ),
                )
            )
        if metadata:
            issues.extend(
                persisted_analysis_coverage_issues(
                    self.root, active_index_backend(root=self.root)
                )
            )
        return self._envelope(
            {
                "indexed": bool(metadata),
                "usable": bool(metadata) and not empty_index,
                "metadata": metadata if detail else self._compact_metadata(metadata),
                "generation": (
                    None
                    if generation is None
                    else {
                        "number": generation.generation,
                        "state": generation.state,
                        "partial": generation.partial,
                        "failed_file_count": generation.failed_file_count,
                    }
                ),
                "coverage": {
                    "status": "complete" if not issues else "incomplete",
                    "issue_count": len(issues),
                    "issues": [self._coverage_payload(issue) for issue in issues]
                    if detail
                    else [],
                },
                "runtime": runtime_identity(),
            }
        )

    def symbols(
        self,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """List bounded deterministic symbol inventory rows.

        Parameters
        ----------
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of inventory entries to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing structural symbol inventory rows.
        """
        rows, page = self._page_rows(
            self._query(
                lambda conn: symbol_inventory(
                    self.root,
                    limit=_REPOSITORY_MAP_INVENTORY_LIMIT + 1,
                    conn=conn,
                )
            ),
            cursor,
            limit,
            binding="symbols",
        )
        return self._envelope(
            {"symbols": [self._inventory_payload(row) for row in rows]},
            page=page,
            output_budget=output_budget,
        )

    def references(
        self,
        name: str,
        *,
        direction: str = "outgoing",
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return callable references in one requested direction.

        Parameters
        ----------
        name : str
            Exact logical callable name to inspect.
        direction : str, optional
            ``"incoming"`` for owners that reference ``name`` or
            ``"outgoing"`` for targets referenced by ``name``.
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic reference rows to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing callable-reference rows.

        Raises
        ------
        ValueError
            If ``direction`` or ``limit`` is outside the contract bounds.
        """
        incoming = self._incoming_direction(direction)
        rows, page = self._page_rows(
            self._query(
                lambda conn: find_callable_refs(
                    EdgeQueryRequest(
                        root=self.root,
                        name=name,
                        incoming=incoming,
                        conn=conn,
                    )
                )
            ),
            cursor,
            limit,
            binding=f"references:{name}:{direction}",
        )
        return self._envelope(
            {
                "references": [
                    self._relation_payload(
                        row,
                        source_prefix="owner",
                        target_prefix="target",
                    )
                    for row in rows
                ]
            },
            page=page,
            output_budget=output_budget,
        )

    def callers(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return static callers for one exact logical callable name.

        Parameters
        ----------
        name : str
            Exact logical callee name to inspect.
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic call-edge rows to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing incoming static call edges.
        """
        return self._call_edges(
            name, incoming=True, cursor=cursor, limit=limit, output_budget=output_budget
        )

    def callees(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return static callees for one exact logical caller name.

        Parameters
        ----------
        name : str
            Exact logical caller name to inspect.
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic call-edge rows to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing outgoing static call edges.
        """
        return self._call_edges(
            name,
            incoming=False,
            cursor=cursor,
            limit=limit,
            output_budget=output_budget,
        )

    def documentation_findings(
        self,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return bounded documentation-audit findings from the active route.

        Parameters
        ----------
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic findings to return.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing normalized audit findings.
        """
        rows, page = self._page_rows(
            self._query(lambda conn: docstring_issues(self.root, conn=conn)),
            cursor,
            limit,
            binding="documentation_findings",
        )
        return self._envelope(
            {"findings": [self._finding_payload(row) for row in rows]},
            page=page,
            output_budget=output_budget,
        )

    def context_for_task(
        self,
        query: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
        search_profile: str | None = None,
        explain: bool = False,
    ) -> dict[str, object]:
        """Build deterministic repository context for one natural-language task.

        Parameters
        ----------
        query : str
            Task description used by Codira's context retrieval pipeline.
        cursor : str | None, optional
            Continuation cursor emitted for this exact query and index generation.
        limit : int, optional
            Maximum number of complete match and evidence items to return.
        search_profile : str | None, optional
            Configured similarity-search profile; ``None`` selects ``default``.

        explain : bool, optional
            Include detailed retrieval diagnostics when true.

        Returns
        -------
        dict[str, object]
            Contract envelope containing the structured direct-core context.

        Raises
        ------
        ValueError
            If the result limit, profile name, or continuation cursor is invalid.
        TypeError
            If the core context response contains malformed paging data.
        """
        self._validate_limit(limit)
        active_similarity_search_profile(root=self.root, name=search_profile)
        offset = self._context_cursor_offset(
            cursor, query=query, limit=limit, search_profile=search_profile
        )

        def _retrieve(
            conn: BackendQueryConnection | None,
        ) -> dict[str, object]:
            context = json.loads(
                context_for(
                    ContextRequest(
                        root=self.root,
                        query=query,
                        as_json=True,
                        explain=explain,
                        search_profile=search_profile,
                        result_offset=offset,
                        result_limit=limit,
                        complete_context_items=True,
                        conn=conn,
                        max_source_file_bytes=(
                            load_effective_config(
                                root=self.root
                            ).embeddings.indexing.max_source_file_bytes
                        ),
                    )
                )
            )
            matches = cast("list[dict[str, object]]", context.get("top_matches", []))
            evidence = cast("list[list[str]]", context.get("context", []))
            items: list[dict[str, object]] = []
            for index, match in enumerate(matches):
                item = dict(match)
                if item.get("type") == "method":
                    line_number = item.get("lineno")
                    if not isinstance(line_number, int):
                        message = "Core context match returned an invalid line number"
                        raise TypeError(message)
                    row: SymbolRow = (
                        str(item["type"]),
                        str(item["module"]),
                        str(item["name"]),
                        str(item["file"]),
                        line_number,
                    )
                    qualified_name = logical_symbol_name(self.root, row, conn=conn)
                    item["qualified_name"] = qualified_name
                    item["owner"] = qualified_name.rpartition(".")[0]
                item["evidence"] = evidence[index] if index < len(evidence) else []
                if item.get("type") != "documentation":
                    item["identity"] = symbol_identity(
                        self.root,
                        (
                            str(item["type"]),
                            str(item["module"]),
                            str(item["name"]),
                            str(item["file"]),
                            int(str(item["lineno"])),
                        ),
                    )
                item["evidence_kind"] = "discovery_snippet"
                item["file"] = self._trusted_relative_path(str(item["file"]))
                items.append(item)
            page_info = cast("dict[str, object]", context.get("page", {}))
            return {
                "status": context.get("status"),
                "items": items,
                "_total": page_info.get("total", 0),
                **({"explain": context.get("explain")} if explain else {}),
            }

        result = self._query(_retrieve)
        total_value = result.pop("_total", 0)
        if not isinstance(total_value, int):
            message = "Core context page returned an invalid total count"
            raise TypeError(message)
        total = total_value
        next_offset = offset + len(cast("list[object]", result["items"]))
        has_more = next_offset < total
        next_cursor = (
            self._encode_context_cursor(
                query=query,
                limit=limit,
                search_profile=search_profile,
                offset=next_offset,
            )
            if has_more
            else None
        )
        page: dict[str, object] = {
            "offset": offset,
            "limit": limit,
            "total": total,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
        return self._envelope(
            result,
            page=page,
            truncation={"truncated": False, "reasons": []},
            output_budget=None,
        )

    def impact_analysis(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Inspect structural callers and references that can affect a symbol.

        Parameters
        ----------
        name : str
            Exact symbol name to inspect for structural impact.
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of deterministic rows per impact category.
        output_budget : int, optional
            Deprecated compatibility argument; whole items are never clipped.

        Returns
        -------
        dict[str, object]
            Contract envelope containing matching symbols and incoming graph
            relations that depend on them.
        """
        symbols = self._query(lambda conn: find_symbol(self.root, name, conn=conn))
        calls = self._query(
            lambda conn: find_call_edges(
                EdgeQueryRequest(root=self.root, name=name, incoming=True, conn=conn)
            )
        )
        references = self._query(
            lambda conn: find_callable_refs(
                EdgeQueryRequest(root=self.root, name=name, incoming=True, conn=conn)
            )
        )
        items = [dict(self._symbol_payload(row), category="symbol") for row in symbols]
        items.extend(
            dict(
                self._relation_payload(
                    row, source_prefix="caller", target_prefix="callee"
                ),
                category="call",
            )
            for row in calls
        )
        items.extend(
            dict(
                self._relation_payload(
                    row, source_prefix="owner", target_prefix="target"
                ),
                category="reference",
            )
            for row in references
        )
        selected, page = self._page_rows(items, cursor, limit, binding=f"impact:{name}")
        return self._envelope(
            {
                "items": selected,
                "coverage": {
                    "dynamic_complete": False,
                    "relation_provenance": "static_analyzer",
                },
            },
            page=page,
            output_budget=output_budget,
        )

    def repository_map(
        self,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return a compact, provenance-rich map of indexed repository modules.

        Parameters
        ----------
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of module summaries to include.
        output_budget : int, optional
            Maximum serialized character count for the ``result`` payload.

        Returns
        -------
        dict[str, object]
            Contract envelope containing deterministic module summaries and
            explicit truncation metadata.

        Raises
        ------
        ValueError
            If ``limit`` or ``output_budget`` is outside the contract bounds.
        """
        self._validate_limit(limit)
        self._validate_output_budget(output_budget)
        rows = self._query(
            lambda conn: symbol_inventory(
                self.root,
                limit=_REPOSITORY_MAP_INVENTORY_LIMIT + 1,
                conn=conn,
            )
        )
        source_truncated = len(rows) > _REPOSITORY_MAP_INVENTORY_LIMIT
        if source_truncated:
            rows = rows[:_REPOSITORY_MAP_INVENTORY_LIMIT]

        modules = self._repository_map_modules(rows)
        selected_modules, page = self._page_rows(
            modules, cursor, limit, binding="repository_map"
        )
        selected, budget_truncated = self._budgeted_modules(
            selected_modules, output_budget
        )

        result: dict[str, object] = {"modules": selected}
        reasons = [
            reason
            for truncated, reason in (
                (source_truncated, "source_inventory_limit"),
                (budget_truncated, "output_budget"),
            )
            if truncated
        ]
        return self._envelope(
            result,
            page=page,
            truncation={
                "truncated": bool(reasons),
                "reasons": reasons,
                "estimated_output_size": len(json.dumps(result, sort_keys=True)),
            },
        )

    def arch(
        self,
        *,
        cursor: str | None = None,
        limit: int = 10,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Return a bounded, read-only architecture model from the index.

        Parameters
        ----------
        cursor : str | None, optional
            Continuation cursor emitted by a prior response.
        limit : int, optional
            Maximum number of module inventory entries to return.
        output_budget : int, optional
            Maximum serialized character count for the result payload.

        Returns
        -------
        dict[str, object]
            Contract envelope containing a paginated architecture model.

        Raises
        ------
        ValueError
            If ``limit`` or ``output_budget`` is outside the contract bounds.

        Notes
        -----
        This method never writes report artifacts. The CLI ``codira arch``
        command remains the file-producing interface.
        """
        self._validate_limit(limit)
        self._validate_output_budget(output_budget)
        model = self._query(
            lambda conn: build_architecture_model_from_index(self.root, conn=conn)
        )
        modules, page = self._page_rows(
            list(model.modules), cursor, limit, binding="arch"
        )
        result, budget_truncated = self._budgeted_architecture_model(
            model,
            tuple(modules),
            output_budget,
        )
        reasons = [
            reason
            for truncated, reason in ((budget_truncated, "output_budget"),)
            if truncated
        ]
        return self._envelope(
            result,
            page=page,
            truncation={
                "truncated": bool(reasons),
                "reasons": reasons,
                "estimated_output_size": len(json.dumps(result, sort_keys=True)),
            },
        )

    def emb(
        self,
        query: str,
        *,
        prefix: str | None = None,
        cursor: str | None = None,
        limit: int = 10,
        search_profile: str | None = None,
    ) -> dict[str, object]:
        """Search stored symbol embeddings without vector-store maintenance.

        Parameters
        ----------
        query : str
            Natural-language text to score against indexed symbols.
        prefix : str | None, optional
            Repository-relative path prefix restricting candidate files.
        cursor : str or None, optional
            Query, profile, candidate and generation-bound continuation.
        limit : int, optional
            Maximum number of ranked embedding matches to return.
        search_profile : str | None, optional
            Named similarity-index profile, or the configured default.

        Returns
        -------
        dict[str, object]
            Contract envelope containing ranked embedding matches.

        Raises
        ------
        ValueError
            If ``limit`` is outside contract bounds, or
            ``prefix`` escapes the trusted repository root.

        Notes
        -----
        This is intentionally search-only. It does not expose ``emb purge`` or
        any vector-store maintenance operation.
        """
        self._validate_limit(limit)
        normalized_prefix = normalize_prefix(self.root, prefix)
        matches = self._query(
            lambda conn: embedding_candidates(
                EmbeddingCandidatesRequest(
                    root=self.root,
                    query=query,
                    limit=100,
                    min_score=0.0,
                    prefix=normalized_prefix,
                    search_profile=search_profile,
                    conn=conn,
                )
            )
        )
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        rows, page = self._page_rows(
            [
                self._embedding_payload(match, candidate)
                for match, candidate in zip(matches, resolved, strict=True)
            ],
            cursor,
            limit,
            binding=f"emb:{query}:{prefix}:{search_profile}",
        )
        return self._envelope(
            {
                "matches": rows,
                "candidate_scope": "up to 100 ranked candidates",
                "similarity": (
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            },
            page=page,
            output_budget=None,
        )

    def docs(
        self,
        query: str,
        *,
        prefix: str | None = None,
        cursor: str | None = None,
        limit: int = 10,
        search_profile: str | None = None,
    ) -> dict[str, object]:
        """Search stored documentation embeddings without mutating the index.

        Parameters
        ----------
        query : str
            Natural-language text to score against indexed documentation.
        prefix : str | None, optional
            Repository-relative path prefix restricting candidate documents.
        cursor : str or None, optional
            Query, profile, candidate and generation-bound continuation.
        limit : int, optional
            Maximum number of ranked documentation matches to return.
        search_profile : str | None, optional
            Named similarity-index profile, or the configured default.

        Returns
        -------
        dict[str, object]
            Contract envelope containing ranked documentation matches.

        Raises
        ------
        ValueError
            If ``limit`` is outside contract bounds, or
            ``prefix`` escapes the trusted repository root.
        """
        self._validate_limit(limit)
        normalized_prefix = normalize_prefix(self.root, prefix)
        matches = self._query(
            lambda conn: documentation_candidates(
                DocumentationCandidatesRequest(
                    root=self.root,
                    query=query,
                    limit=100,
                    min_score=0.0,
                    prefix=normalized_prefix,
                    search_profile=search_profile,
                    conn=conn,
                )
            )
        )
        similarity = getattr(matches, "search_result", None)
        resolved = getattr(matches, "resolved", ())
        if similarity is None:
            resolved = tuple(None for _ in matches)
        rows, page = self._page_rows(
            [
                self._documentation_payload(match, candidate)
                for match, candidate in zip(matches, resolved, strict=True)
            ],
            cursor,
            limit,
            binding=f"docs:{query}:{prefix}:{search_profile}",
        )
        return self._envelope(
            {
                "matches": rows,
                "candidate_scope": "up to 100 ranked candidates",
                "similarity": (
                    None
                    if similarity is None
                    else similarity_query_provenance_payload(similarity)
                ),
            },
            page=page,
            output_budget=None,
        )

    @staticmethod
    def _architecture_result(
        model: ArchitectureModel,
        modules: tuple[ArchitectureModule, ...],
    ) -> dict[str, object]:
        """Build a self-contained architecture payload for selected modules.

        Parameters
        ----------
        model : codira.architecture.ArchitectureModel
            Architecture model with deterministic dataclass collections.
        modules : tuple[codira.architecture.ArchitectureModule, ...]
            Selected architecture module entries.

        Returns
        -------
        dict[str, object]
            JSON-compatible model summary and relations scoped to the modules.
        """
        selected_names = {module.name for module in modules}
        dependencies = tuple(
            dependency
            for dependency in model.dependencies
            if dependency.source in selected_names
            and dependency.destination in selected_names
        )
        cycles = tuple(
            cycle for cycle in model.cycles if set(cycle.members) <= selected_names
        )
        metrics = tuple(
            metric for metric in model.metrics if metric.module in selected_names
        )
        result = {
            "summary": {
                "modules": len(model.modules),
                "dependencies": len(model.dependencies),
                "cycles": len(model.cycles),
            },
            "modules": [asdict(module) for module in modules],
            "dependencies": [asdict(dependency) for dependency in dependencies],
            "cycles": [asdict(cycle) for cycle in cycles],
            "metrics": [asdict(metric) for metric in metrics],
        }
        return cast("dict[str, object]", json.loads(json.dumps(result)))

    @classmethod
    def _budgeted_architecture_model(
        cls,
        model: ArchitectureModel,
        modules: tuple[ArchitectureModule, ...],
        output_budget: int,
    ) -> tuple[dict[str, object], bool]:
        """Fit a deterministic architecture-module prefix into an MCP budget.

        Parameters
        ----------
        model : codira.architecture.ArchitectureModel
            Complete deterministic architecture model.
        modules : tuple[codira.architecture.ArchitectureModule, ...]
            One paginated module selection in deterministic order.
        output_budget : int
            Maximum serialized character count requested by the client.

        Returns
        -------
        tuple[dict[str, object], bool]
            Self-contained payload and whether any selected module was omitted.
        """
        return cls._architecture_result(model, modules), False

    def _call_edges(
        self,
        name: str,
        *,
        incoming: bool,
        cursor: str | None,
        limit: int,
        output_budget: int,
    ) -> dict[str, object]:
        """Return bounded static call edges in one direction.

        Parameters
        ----------
        name : str
            Exact logical name used to select call edges.
        incoming : bool
            Whether the result selects callers instead of callees.
        limit : int
            Maximum number of deterministic call-edge rows to return.

        Returns
        -------
        dict[str, object]
            Contract envelope containing normalized static call-edge rows.
        """
        rows, page = self._page_rows(
            self._query(
                lambda conn: find_call_edges(
                    EdgeQueryRequest(
                        root=self.root,
                        name=name,
                        incoming=incoming,
                        conn=conn,
                    )
                )
            ),
            cursor,
            limit,
            binding=f"calls:{name}:{incoming}",
        )
        return self._envelope(
            {
                "calls": [
                    self._relation_payload(
                        row,
                        source_prefix="caller",
                        target_prefix="callee",
                    )
                    for row in rows
                ]
            },
            page=page,
            output_budget=output_budget,
        )

    def _query(
        self,
        operation: Callable[[BackendQueryConnection | None], _QueryResult],
    ) -> _QueryResult:
        """Run a structural read through the optional warm executor.

        Parameters
        ----------
        operation : collections.abc.Callable
            Read operation accepting a warm connection or ``None`` for the
            existing direct-core path.

        Returns
        -------
        object
            Result produced by the operation.

        Raises
        ------
        ValueError
            If the persisted index is absent or contains zero files.
        """
        metadata = _read_metadata_file(get_metadata_path(self.root))
        indexed_file_count = metadata.get("indexed_file_count")
        if (
            not isinstance(indexed_file_count, str)
            or not indexed_file_count.isdecimal()
            or int(indexed_file_count) < 1
        ):
            msg = "Codira index is unavailable or contains zero files"
            raise ValueError(msg)
        if self.query_executor is None:
            return operation(None)
        return self.query_executor.execute(operation)

    def _envelope(
        self,
        result: dict[str, object],
        *,
        page: dict[str, object] | None = None,
        truncation: dict[str, object] | None = None,
        output_budget: int | None = DEFAULT_OUTPUT_BUDGET,
    ) -> dict[str, object]:
        """Wrap a direct core result in the common MCP response envelope.

        Parameters
        ----------
        result : dict[str, object]
            JSON-compatible direct core result.
        page : dict[str, object] | None, optional
            Pagination metadata for a bounded result set.
        truncation : dict[str, object] | None, optional
            Explicit result-truncation metadata.

        Returns
        -------
        dict[str, object]
            Versioned response envelope with provenance and freshness metadata.
        """
        if output_budget is not None:
            self._validate_output_budget(output_budget)
        resolved_truncation: dict[str, object] = {"truncated": False, "reasons": []}
        if truncation is not None:
            resolved_truncation.update(truncation)
        generation = self._ready_generation_record()
        provenance: dict[str, object] = {
            "source": "codira-core",
            "repository": self.root.name,
            "trusted_root": ".",
            "execution_mode": "direct",
            "generation": None if generation is None else generation.generation,
        }
        if generation is not None and generation.partial:
            provenance["partial_index_warning"] = {
                "failed_file_count": generation.failed_file_count,
                "message": "The ready index omitted one or more failed source files.",
            }
        if self.startup_provenance is not None:
            provenance.update(self.startup_provenance)
        return {
            "contract_version": MCP_CONTRACT_VERSION,
            "result": result,
            "provenance": provenance,
            "freshness": self._compact_metadata(
                _read_metadata_file(get_metadata_path(self.root))
            ),
            "page": {} if page is None else page,
            "truncation": resolved_truncation,
        }

    def _generation(self) -> int | None:
        """Return the current ready generation for direct-core provenance.

        Parameters
        ----------
        None

        Returns
        -------
        int | None
            Ready durable generation, or ``None`` when unavailable.
        """
        record = self._ready_generation_record()
        return None if record is None else record.generation

    def _ready_generation_record(self) -> IndexGeneration | None:
        """Return the current ready generation record when available.

        Parameters
        ----------
        None

        Returns
        -------
        codira.index_generation.IndexGeneration | None
            Ready durable generation record, or ``None`` when unavailable.
        """
        record = IndexGenerationStore(self.root).read()
        return None if record is None or record.state != "ready" else record

    def _page_rows(
        self,
        rows: list[_Row],
        cursor: str | None,
        limit: int,
        *,
        binding: str = "inventory",
    ) -> tuple[list[_Row], dict[str, object]]:
        """Select one deterministic page without accepting repository paths.

        Parameters
        ----------
        rows : list[object]
            Fully ordered direct-core rows.
        cursor : str | None
            Opaque offset cursor from a prior response.
        limit : int
            Maximum row count for the page.

        Returns
        -------
        tuple[list[object], dict[str, object]]
            Selected rows and continuation metadata.

        Raises
        ------
        ValueError
            If the cursor or limit is invalid.
        """
        self._validate_limit(limit)
        query = (
            binding
            + ":"
            + hashlib.sha256(
                json.dumps(rows, sort_keys=True, default=str).encode()
            ).hexdigest()
        )
        offset = self._context_cursor_offset(
            cursor, query=query, limit=limit, search_profile=None
        )
        selected = rows[offset : offset + limit]
        next_offset = offset + len(selected)
        return selected, {
            "offset": offset,
            "limit": limit,
            "total": len(rows),
            "has_more": next_offset < len(rows),
            "next_cursor": (
                self._encode_context_cursor(
                    query=query, limit=limit, search_profile=None, offset=next_offset
                )
                if next_offset < len(rows)
                else None
            ),
        }

    @staticmethod
    def _cursor_offset(cursor: str | None) -> int:
        """Decode the adapter's opaque deterministic offset cursor.

        Parameters
        ----------
        cursor : str | None
            Continuation value emitted by a prior response.

        Returns
        -------
        int
            Non-negative row offset.

        Raises
        ------
        ValueError
            If the cursor is malformed.
        """
        if cursor is None or cursor == "":
            return 0
        prefix, separator, value = cursor.partition(":")
        if prefix != "offset" or separator != ":" or not value.isdecimal():
            msg = "cursor must be an MCP continuation cursor"
            raise ValueError(msg)
        return int(value)

    def _context_cursor_offset(
        self,
        cursor: str | None,
        *,
        query: str,
        limit: int,
        search_profile: str | None,
    ) -> int:
        """Validate and decode a cursor bound to one context search.

        Parameters
        ----------
        cursor : str | None
            Continuation cursor emitted by a prior context response.
        query : str
            Exact natural-language query for this page sequence.
        limit : int
            Page size for this sequence.
        search_profile : str | None
            Selected similarity-search profile.

        Returns
        -------
        int
            Offset of the next context item.

        Raises
        ------
        ValueError
            If the cursor is malformed or belongs to another search state.
        """
        if cursor is None or cursor == "":
            return 0
        prefix, separator, encoded = cursor.partition(":")
        if prefix != "ctx" or not separator:
            message = f"cursor must be a context continuation cursor. {CURSOR_GUIDANCE}"
            raise ValueError(message)
        try:
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=="))
        except (ValueError, json.JSONDecodeError) as error:
            message = f"context cursor is malformed. {CURSOR_GUIDANCE}"
            raise ValueError(message) from error
        expected = {
            "root": hashlib.sha256(str(self.root).encode()).hexdigest(),
            "query": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "profile": search_profile or "default",
            "serving_source": runtime_identity()["source_sha256"],
            "configuration": hashlib.sha256(
                json.dumps(
                    asdict(load_effective_config(root=self.root)),
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
            "limit": limit,
            "generation": self._generation(),
        }
        if not isinstance(payload, dict) or any(
            payload.get(key) != value for key, value in expected.items()
        ):
            message = (
                f"context cursor does not match this query or index. {CURSOR_GUIDANCE}"
            )
            raise ValueError(message)
        offset = payload.get("offset")
        if not isinstance(offset, int) or offset < 0:
            message = "context cursor offset is invalid"
            raise ValueError(message)
        return offset

    def _encode_context_cursor(
        self,
        *,
        query: str,
        limit: int,
        search_profile: str | None,
        offset: int,
    ) -> str:
        """Encode a stable continuation cursor for one context page sequence.

        Parameters
        ----------
        query : str
            Exact natural-language query for this sequence.
        limit : int
            Page size for this sequence.
        search_profile : str | None
            Selected similarity-search profile.
        offset : int
            Next item offset.

        Returns
        -------
        str
            URL-safe opaque context cursor.
        """
        payload = {
            "root": hashlib.sha256(str(self.root).encode()).hexdigest(),
            "query": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "profile": search_profile or "default",
            "serving_source": runtime_identity()["source_sha256"],
            "configuration": hashlib.sha256(
                json.dumps(
                    asdict(load_effective_config(root=self.root)),
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
            "limit": limit,
            "generation": self._generation(),
            "offset": offset,
        }
        encoded = (
            base64.urlsafe_b64encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        return f"ctx:{encoded}"

    def _embedding_payload(
        self,
        match: ScoredSymbol,
        resolved: SimilarityResolvedCandidate | None,
    ) -> dict[str, object]:
        """Normalize one ranked symbol embedding match for MCP.

        Parameters
        ----------
        match : codira.types.ScoredSymbol
            Similarity score and indexed symbol row.

        Returns
        -------
        dict[str, object]
            JSON-compatible score and trusted symbol location fields.
        """
        score, (symbol_type, module, name, file_path, lineno) = match
        payload: dict[str, object] = {
            "score": round(score, 2),
            "type": symbol_type,
            "module": module,
            "name": name,
            "file": self._trusted_relative_path(file_path),
            "line": lineno,
        }
        if symbol_type == "method":
            row: SymbolRow = (symbol_type, module, name, file_path, lineno)
            qualified_name = logical_symbol_name(self.root, row)
            payload["qualified_name"] = qualified_name
            payload["owner"] = qualified_name.rpartition(".")[0]
        if resolved is not None:
            payload["similarity"] = similarity_candidate_provenance_payload(
                resolved.candidate
            )
        return payload

    def _documentation_payload(
        self,
        match: ScoredDocumentation,
        resolved: SimilarityResolvedCandidate | None,
    ) -> dict[str, object]:
        """Normalize one ranked documentation embedding match for MCP.

        Parameters
        ----------
        match : codira.types.ScoredDocumentation
            Similarity score and indexed documentation row.

        Returns
        -------
        dict[str, object]
            JSON-compatible score, source, and documentation fields.
        """
        (
            score,
            (
                stable_id,
                kind,
                source_format,
                file_path,
                lineno,
                end_lineno,
                title,
                heading_path,
                text,
            ),
        ) = match
        payload: dict[str, object] = {
            "score": round(score, 2),
            "stable_id": stable_id,
            "kind": kind,
            "source_format": source_format,
            "file": self._trusted_relative_path(file_path),
            "line": lineno,
            "end_line": end_lineno,
            "title": title,
            "heading_path": list(heading_path),
            "text": text,
        }
        if resolved is not None:
            payload["similarity"] = similarity_candidate_provenance_payload(
                resolved.candidate
            )
        return payload

    def _symbol_payload(self, row: SymbolRow) -> dict[str, object]:
        """Normalize a structural symbol row for the MCP response payload.

        Parameters
        ----------
        row : codira.types.SymbolRow
            Ordered direct-query symbol row.

        Returns
        -------
        dict[str, object]
            Named, JSON-compatible structural symbol fields.
        """
        kind, module, name, file, line = row
        payload = {
            "module": module,
            "name": name,
            "kind": kind,
            "file": self._trusted_relative_path(file),
            "line": line,
            "identity": symbol_identity(self.root, row),
            "canonical_name": f"{module}.{logical_symbol_name(self.root, row)}",
        }
        if kind == "method" or "." in name:
            qualified_name = logical_symbol_name(self.root, row)
            payload["qualified_name"] = qualified_name
            payload["owner"] = qualified_name.rpartition(".")[0]
        return payload

    @staticmethod
    def _compact_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
        """Select small freshness fields from persisted metadata.

        Parameters
        ----------
        metadata : collections.abc.Mapping[str, object]
            Complete persisted index metadata.

        Returns
        -------
        dict[str, object]
            Stable schema, backend, commit and indexed-file count.
        """
        return {
            key: metadata[key]
            for key in (
                "schema_version",
                "backend_name",
                "backend_version",
                "commit",
                "indexed_file_count",
            )
            if key in metadata
        }

    @staticmethod
    def _coverage_payload(issue: CoverageIssue) -> dict[str, object]:
        """Normalize one coverage diagnostic for an MCP result.

        Parameters
        ----------
        issue : codira.indexer.CoverageIssue
            Analyzer-coverage diagnostic to serialize.

        Returns
        -------
        dict[str, object]
            JSON-compatible coverage diagnostic fields.
        """
        return {
            "path": issue.path,
            "directory": issue.directory,
            "suffix": issue.suffix,
            "reason": issue.reason,
        }

    def _repository_map_modules(
        self,
        rows: list[BackendSymbolInventoryItem],
    ) -> list[dict[str, object]]:
        """Aggregate direct-core inventory rows into deterministic module summaries.

        Parameters
        ----------
        rows : list[codira.contracts.BackendSymbolInventoryItem]
            Bounded direct-core symbol inventory rows.

        Returns
        -------
        list[dict[str, object]]
            Sorted module summaries with source-file provenance and symbol-kind
            counts.
        """
        modules: dict[str, dict[str, object]] = {}
        for row in rows:
            entry = modules.setdefault(
                row.module,
                {
                    "module": row.module,
                    "files": set(),
                    "symbol_count": 0,
                    "symbol_kinds": {},
                },
            )
            files = cast("set[str]", entry["files"])
            kinds = cast("dict[str, int]", entry["symbol_kinds"])
            files.add(row.file)
            entry["symbol_count"] = cast("int", entry["symbol_count"]) + 1
            kinds[row.symbol_type] = kinds.get(row.symbol_type, 0) + 1

        return [
            {
                "module": module,
                "files": sorted(
                    self._trusted_relative_path(file)
                    for file in cast("set[str]", entry["files"])
                ),
                "symbol_count": entry["symbol_count"],
                "symbol_kinds": dict(
                    sorted(cast("dict[str, int]", entry["symbol_kinds"]).items())
                ),
            }
            for module, entry in sorted(modules.items())
        ]

    @staticmethod
    def _budgeted_modules(
        modules: list[dict[str, object]],
        output_budget: int,
    ) -> tuple[list[dict[str, object]], bool]:
        """Select the longest deterministic module prefix within a character budget.

        Parameters
        ----------
        modules : list[dict[str, object]]
            Deterministically sorted module summaries.
        output_budget : int
            Maximum serialized character count for the result payload.

        Returns
        -------
        tuple[list[dict[str, object]], bool]
            Selected module summaries and whether the budget omitted any.
        """
        return modules, False

    @staticmethod
    def _graph_metric_payload(metric: BackendGraphMetric) -> dict[str, int]:
        """Normalize one graph connectivity metric for an MCP result.

        Parameters
        ----------
        metric : codira.contracts.BackendGraphMetric
            Direct-core graph metric to serialize.

        Returns
        -------
        dict[str, int]
            Total and unresolved edge counts.
        """
        return {"total": metric.total, "unresolved": metric.unresolved}

    def _inventory_payload(self, item: BackendSymbolInventoryItem) -> dict[str, object]:
        """Normalize a graph-enriched symbol inventory item.

        Parameters
        ----------
        item : codira.contracts.BackendSymbolInventoryItem
            Direct-core inventory item to serialize.

        Returns
        -------
        dict[str, object]
            JSON-compatible symbol and graph-metric fields.
        """
        payload: dict[str, object] = {
            "type": item.symbol_type,
            "module": item.module,
            "name": item.name,
            "file": self._trusted_relative_path(item.file),
            "line": item.lineno,
            "calls_out": self._graph_metric_payload(item.calls_out),
            "calls_in": self._graph_metric_payload(item.calls_in),
            "references_out": self._graph_metric_payload(item.refs_out),
            "references_in": self._graph_metric_payload(item.refs_in),
        }
        if item.symbol_type == "method":
            row: SymbolRow = (
                item.symbol_type,
                item.module,
                item.name,
                item.file,
                item.lineno,
            )
            qualified_name = logical_symbol_name(self.root, row)
            payload["qualified_name"] = qualified_name
            payload["owner"] = qualified_name.rpartition(".")[0]
        return payload

    @staticmethod
    def _relation_payload(
        row: tuple[str, str, str | None, str | None, str | None, str | None, int],
        *,
        source_prefix: str,
        target_prefix: str,
    ) -> dict[str, object]:
        """Normalize one call or reference edge without invoking the CLI.

        Parameters
        ----------
        row : tuple[str, str, str | None, str | None, str | None, str | None, int]
            Direct-core relation row.
        source_prefix : str
            Semantic prefix for the source endpoint fields.
        target_prefix : str
            Semantic prefix for the target endpoint fields.

        Returns
        -------
        dict[str, object]
            JSON-compatible relation endpoints and resolution metadata.
        """
        (
            source_module,
            source_name,
            target_module,
            target_name,
            external_target_kind,
            external_target_name,
            resolved,
        ) = row
        result: dict[str, object] = {
            f"{source_prefix}_module": source_module,
            f"{source_prefix}_name": source_name,
            f"{target_prefix}_module": target_module,
            f"{target_prefix}_name": target_name,
            "resolved": bool(resolved),
        }
        if external_target_kind is not None:
            result["external_target_kind"] = external_target_kind
        if external_target_name is not None:
            result["external_target_name"] = external_target_name
        return result

    def _finding_payload(self, row: DocstringIssueRow) -> dict[str, object]:
        """Normalize one documentation-audit finding for an MCP result.

        Parameters
        ----------
        row : codira.types.DocstringIssueRow
            Direct-core documentation-audit row to serialize.

        Returns
        -------
        dict[str, object]
            JSON-compatible finding, route, and source-location fields.
        """
        (
            issue_type,
            message,
            audit_language,
            audit_plugin_name,
            audit_plugin_version,
            convention_name,
            convention_version,
            rule_id,
            severity,
            stable_id,
            symbol_type,
            module_name,
            symbol_name,
            file_path,
            lineno,
            end_lineno,
        ) = row
        return {
            "type": issue_type,
            "message": message,
            "audit_plugin": {
                "name": audit_plugin_name,
                "version": audit_plugin_version,
            },
            "audit_convention": {
                "name": convention_name,
                "version": convention_version,
            },
            "audit_route": {
                "language": audit_language,
                "convention": convention_name,
                "plugin": audit_plugin_name,
            },
            "rule_id": rule_id,
            "severity": severity,
            "stable_id": stable_id,
            "symbol_type": symbol_type,
            "module": module_name,
            "name": symbol_name,
            "file": self._trusted_relative_path(file_path),
            "line": lineno,
            "end_line": end_lineno,
        }

    def _trusted_relative_path(self, value: str) -> str:
        """Render an indexed path only when it remains inside the trusted root.

        Parameters
        ----------
        value : str
            Indexed source path emitted by a direct-core query.

        Returns
        -------
        str
            Repository-relative POSIX path.

        Raises
        ------
        ValueError
            If the indexed path escapes the startup-trusted repository root.
        """
        candidate = Path(value)
        resolved = (
            (self.root / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        try:
            return resolved.relative_to(self.root).as_posix()
        except ValueError as error:
            msg = "indexed path escapes the MCP trusted repository root"
            raise ValueError(msg) from error

    @staticmethod
    def _incoming_direction(direction: str) -> bool:
        """Convert a contract direction value into a direct-query flag.

        Parameters
        ----------
        direction : str
            Contract direction value.

        Returns
        -------
        bool
            ``True`` for incoming traversal and ``False`` for outgoing.

        Raises
        ------
        ValueError
            If ``direction`` is not one of the contract values.
        """
        if direction == "incoming":
            return True
        if direction == "outgoing":
            return False
        msg = "direction must be incoming or outgoing"
        raise ValueError(msg)

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Validate a bounded result limit shared by MCP tools.

        Parameters
        ----------
        limit : int
            Requested maximum number of result rows.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If ``limit`` is outside the published contract range.
        """
        if not _MIN_RESULT_LIMIT <= limit <= _MAX_RESULT_LIMIT:
            msg = f"limit must be between {_MIN_RESULT_LIMIT} and {_MAX_RESULT_LIMIT}"
            raise ValueError(msg)

    @staticmethod
    def _validate_output_budget(output_budget: int) -> None:
        """Validate the contract output budget used by the repository map.

        Parameters
        ----------
        output_budget : int
            Maximum serialized character count requested by the client.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If ``output_budget`` is outside the published contract range.
        """
        if not 1 <= output_budget <= MAX_OUTPUT_BUDGET:
            msg = f"output_budget must be between 1 and {MAX_OUTPUT_BUDGET}"
            raise ValueError(msg)
