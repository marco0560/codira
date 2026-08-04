"""Adapt Codira core queries to the local read-only MCP contract.

The adapter owns a repository root selected when the server starts. MCP tool
requests never accept repository paths and delegate directly to core APIs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar, cast

from codira.capabilities import build_capability_contract
from codira.indexer import audit_repo_coverage
from codira.mcp.contract import (
    DEFAULT_OUTPUT_BUDGET,
    MAX_OUTPUT_BUDGET,
    MCP_CONTRACT_VERSION,
    build_contract_document,
)
from codira.query.context import ContextRequest, context_for
from codira.query.exact import (
    EdgeQueryRequest,
    docstring_issues,
    find_call_edges,
    find_callable_refs,
    find_symbol,
    symbol_inventory,
)
from codira.storage import _read_metadata_file, get_metadata_path

if TYPE_CHECKING:
    from codira.contracts import BackendGraphMetric, BackendSymbolInventoryItem
    from codira.indexer import CoverageIssue
    from codira.types import DocstringIssueRow, SymbolRow


_MIN_RESULT_LIMIT = 1
_MAX_RESULT_LIMIT = 100
_REPOSITORY_MAP_INVENTORY_LIMIT = 10_000
_Row = TypeVar("_Row")


@dataclass(frozen=True)
class MCPAdapter:
    """Serve approved MCP operations for one startup-trusted repository root.

    Parameters
    ----------
    root : pathlib.Path
        Existing repository directory selected when the MCP server starts.
    """

    root: Path

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

    def capabilities(self) -> dict[str, object]:
        """Return MCP and Codira capability documents from direct core APIs.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Contract envelope containing MCP and Codira capability documents.
        """
        return self._envelope(
            {
                "mcp": build_contract_document(),
                "codira": build_capability_contract(root=self.root),
            }
        )

    def symbol(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

        Returns
        -------
        dict[str, object]
            Contract envelope containing normalized symbol matches.

        Raises
        ------
        ValueError
            If ``limit`` is outside the contract's supported range.
        """
        rows, page = self._page_rows(find_symbol(self.root, name), cursor, limit)
        return self._envelope(
            {"symbols": [self._symbol_payload(row) for row in rows]},
            page=page,
            output_budget=output_budget,
        )

    def index_status(self) -> dict[str, object]:
        """Return persisted index metadata and current coverage diagnostics.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Contract envelope containing index metadata and coverage findings.
        """
        metadata = _read_metadata_file(get_metadata_path(self.root))
        issues = audit_repo_coverage(self.root)
        return self._envelope(
            {
                "indexed": bool(metadata),
                "metadata": metadata,
                "coverage": {
                    "status": "complete" if not issues else "incomplete",
                    "issues": [self._coverage_payload(issue) for issue in issues],
                },
            }
        )

    def symbols(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

        Returns
        -------
        dict[str, object]
            Contract envelope containing structural symbol inventory rows.
        """
        rows, page = self._page_rows(
            symbol_inventory(self.root, limit=_REPOSITORY_MAP_INVENTORY_LIMIT + 1),
            cursor,
            limit,
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
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

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
            find_callable_refs(
                EdgeQueryRequest(root=self.root, name=name, incoming=incoming)
            ),
            cursor,
            limit,
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
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

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
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

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
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

        Returns
        -------
        dict[str, object]
            Contract envelope containing normalized audit findings.
        """
        rows, page = self._page_rows(docstring_issues(self.root), cursor, limit)
        return self._envelope(
            {"findings": [self._finding_payload(row) for row in rows]},
            page=page,
            output_budget=output_budget,
        )

    def context_for_task(
        self, query: str, *, output_budget: int = DEFAULT_OUTPUT_BUDGET
    ) -> dict[str, object]:
        """Build deterministic repository context for one natural-language task.

        Parameters
        ----------
        query : str
            Task description used by Codira's context retrieval pipeline.
        output_budget : int, optional
            Maximum serialized character count reported for the result.

        Returns
        -------
        dict[str, object]
            Contract envelope containing the structured direct-core context.
        """
        context = json.loads(
            context_for(ContextRequest(root=self.root, query=query, as_json=True))
        )
        return self._envelope({"context": context}, output_budget=output_budget)

    def impact_analysis(
        self,
        name: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
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
            Maximum serialized character count reported for the result.

        Returns
        -------
        dict[str, object]
            Contract envelope containing matching symbols and incoming graph
            relations that depend on them.
        """
        symbols, page = self._page_rows(find_symbol(self.root, name), cursor, limit)
        call_rows, _ = self._page_rows(
            find_call_edges(EdgeQueryRequest(root=self.root, name=name, incoming=True)),
            cursor,
            limit,
        )
        reference_rows, _ = self._page_rows(
            find_callable_refs(
                EdgeQueryRequest(root=self.root, name=name, incoming=True)
            ),
            cursor,
            limit,
        )
        return self._envelope(
            {
                "symbols": [self._symbol_payload(row) for row in symbols],
                "incoming_calls": [
                    self._relation_payload(
                        row,
                        source_prefix="caller",
                        target_prefix="callee",
                    )
                    for row in call_rows
                ],
                "incoming_references": [
                    self._relation_payload(
                        row,
                        source_prefix="owner",
                        target_prefix="target",
                    )
                    for row in reference_rows
                ],
            },
            page=page,
            output_budget=output_budget,
        )

    def repository_map(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
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
        rows = symbol_inventory(self.root, limit=_REPOSITORY_MAP_INVENTORY_LIMIT + 1)
        source_truncated = len(rows) > _REPOSITORY_MAP_INVENTORY_LIMIT
        if source_truncated:
            rows = rows[:_REPOSITORY_MAP_INVENTORY_LIMIT]

        modules = self._repository_map_modules(rows)
        selected_modules, page = self._page_rows(modules, cursor, limit)
        selected, budget_truncated = self._budgeted_modules(
            selected_modules, output_budget
        )

        result: dict[str, object] = {"modules": selected}
        reasons = [
            reason
            for truncated, reason in (
                (source_truncated, "source_inventory_limit"),
                (page["next_cursor"] is not None, "page_limit"),
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
                "output_budget": output_budget,
                "estimated_output_size": len(json.dumps(result, sort_keys=True)),
            },
        )

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
            find_call_edges(
                EdgeQueryRequest(root=self.root, name=name, incoming=incoming)
            ),
            cursor,
            limit,
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

    def _envelope(
        self,
        result: dict[str, object],
        *,
        page: dict[str, object] | None = None,
        truncation: dict[str, object] | None = None,
        output_budget: int = DEFAULT_OUTPUT_BUDGET,
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
        self._validate_output_budget(output_budget)
        estimated_output_size = len(json.dumps(result, sort_keys=True))
        resolved_truncation = {
            "truncated": estimated_output_size > output_budget,
            "reasons": (
                ["output_budget"] if estimated_output_size > output_budget else []
            ),
            "output_budget": output_budget,
            "estimated_output_size": estimated_output_size,
        }
        if truncation is not None:
            resolved_truncation.update(truncation)
        return {
            "contract_version": MCP_CONTRACT_VERSION,
            "result": result,
            "provenance": {
                "source": "codira-core",
                "repository": self.root.name,
                "trusted_root": ".",
            },
            "freshness": _read_metadata_file(get_metadata_path(self.root)),
            "page": {} if page is None else page,
            "truncation": resolved_truncation,
        }

    def _page_rows(
        self, rows: list[_Row], cursor: str | None, limit: int
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
        offset = self._cursor_offset(cursor)
        selected = rows[offset : offset + limit]
        next_offset = offset + len(selected)
        return selected, {
            "limit": limit,
            "next_cursor": (
                f"offset:{next_offset}" if next_offset < len(rows) else None
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
        if cursor is None:
            return 0
        prefix, separator, value = cursor.partition(":")
        if prefix != "offset" or separator != ":" or not value.isdecimal():
            msg = "cursor must be an MCP continuation cursor"
            raise ValueError(msg)
        return int(value)

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
        return {
            "module": module,
            "name": name,
            "kind": kind,
            "file": self._trusted_relative_path(file),
            "line": line,
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
        selected: list[dict[str, object]] = []
        for module in modules:
            candidate = {"modules": [*selected, module]}
            if len(json.dumps(candidate, sort_keys=True)) > output_budget:
                return selected, True
            selected.append(module)
        return selected, False

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
        return {
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
