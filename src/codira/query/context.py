"""Context assembly and rendering for codira query results.

Responsibilities
----------------
- Build retrieval plans, merge symbols, and produce prompt-friendly output that includes doc issues, snippets, and channel diagnostics.
- Coordinate symbol enrichment, embedding summaries, include graph expansion, and diversity heuristics.
- Render final context, explain plans, and collect docstring issues for reporting.

Design principles
-----------------
Context assembly remains deterministic, token-aware, and capped to avoid prompt bloat while keeping evidence transparent.

Architectural role
------------------
This module belongs to the **context rendering layer** that consolidates retrieval results into user-facing text and metadata.
"""

from __future__ import annotations

import ast
import contextlib
import json
import re
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from codira.contracts import (
    split_declared_retrieval_capabilities,
)
from codira.prefix import normalize_prefix, path_has_prefix, prefix_clause
from codira.prompts.default import PromptBuildRequest, build_prompt
from codira.query.classifier import (
    QueryIntent,
    RetrievalPlan,
    build_retrieval_plan,
    classify_query,
)
from codira.query.exact import (
    EdgeQueryRequest,
    docstring_issues,
    find_include_edges,
    find_symbol,
)
from codira.query.graph_enrichment import (
    GraphExpansionRequest,
    expand_graph_related_symbols,
)
from codira.query.producers import (
    CHANNEL_PRODUCER_SPECS,
    EMBEDDING_RETRIEVAL_PRODUCER,
    INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    EmbeddingRetrievalRequest,
    QueryChannelSpec,
    QueryProducerSpec,
    channel_producer_specs,
    selected_enrichment_producers,
)
from codira.query.signals import RetrievalSignal, signal_sort_key
from codira.registry import active_index_backend, active_language_analyzers
from codira.scanner import iter_project_files
from codira.semantic.embeddings import get_embedding_backend
from codira.types import (
    ChannelBundle,
    ChannelName,
    ChannelResults,
    CodeContext,
    IncludeEdgeRow,
    ReferenceRow,
    SymbolRow,
)
from codira.version import package_version

if TYPE_CHECKING:
    from collections.abc import Callable

# Current schema version
SCHEMA_VERSION = "1.1"
# Minimum accepted score
_MIN_SCORE = 1
# Maximum number of rows inspected by the symbol fallback scan.
SYMBOL_FALLBACK_SCAN_LIMIT = 200
# Maximum number of rows retrieved for a token search term.
SYMBOL_TERM_MATCH_LIMIT = 50
# Maximum number of rows inspected by the semantic channel.
SEMANTIC_SCAN_LIMIT = 500
# Maximum number of semantic results returned.
SEMANTIC_RESULT_LIMIT = 50
# Maximum number of embedding results returned.
EMBEDDING_RESULT_LIMIT = 50
# Maximum number of merged symbols returned.
MERGE_RESULT_LIMIT = 10
MERGE_MAX_PER_FILE = 1
MERGE_ROLE_CAPS: dict[FileRole, int] = {
    "implementation": 6,
    "interface": 3,
    "test": 2,
    "tooling": 1,
    "other": 2,
}
MERGE_LANGUAGE_CAPS: dict[str, int] = {
    "python": 4,
    "c": 4,
    "other": 2,
}
# --- token-capped context construction ---
MAX_TOKENS = 1200
# Number of source lines to include in extracted snippets.
SNIPPET_LINE_LIMIT = 6
# Maximum number of lines shown for extracted docstrings in code context.
DOCSTRING_PREVIEW_LINE_LIMIT = 10
# Maximum number of displayed docstring lines in enriched symbol blocks.
DISPLAY_DOCSTRING_LINE_LIMIT = 12
# Maximum number of enriched symbols rendered in text and prompt output.
ENRICHED_CONTEXT_LIMIT = 5
# --- cap doc issues to avoid prompt bloat ---
MAX_ISSUES = 20
# --- weight for semantic consolidation
SEMANTIC_WEIGHT = 0.3
# Minimum accepted embedding similarity.
EMBEDDING_MIN_SCORE = 0.2
CHANNEL_WEIGHTS: dict[ChannelName, float] = {
    "symbol": 1.0,
    "embedding": 1.0,
    "semantic": 1.0,
    "test": 1.0,
    "script": 1.0,
    "call_graph": 0.35,
    "references": 0.3,
    "include_graph": 0.25,
}
MERGE_CROSS_FAMILY_BONUS = 0.15
GRAPH_RETRIEVAL_LIMIT_PER_PRODUCER = 5
FileRole = Literal["implementation", "interface", "test", "tooling", "other"]
SelectionStage = Literal["primary", "deferred"]
DeferralReason = Literal["file_cap", "role_cap", "language_cap"]
DiversityEntry = dict[str, object]
DiversityDiagnostics = dict[str, list[DiversityEntry]]
MergeDiagnosticsEntry = dict[str, object]
MergeDiagnostics = dict[SymbolRow, MergeDiagnosticsEntry]
ExpansionDiagnostics = dict[str, list[dict[str, object]]]
ProducerDiagnosticsEntry = dict[str, object]
SignalCollectionDiagnostics = dict[str, object]


@dataclass(frozen=True)
class GraphRetrievalRequest:
    """
    Request parameters for graph-derived retrieval signals.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    top_matches : list[codira.types.SymbolRow]
        Current retrieval winners used as bounded graph-expansion seeds.
    conn : sqlite3.Connection
        Open database connection reused for exact graph lookups.
    include_include_graph : bool
        Whether include-graph evidence is enabled by the retrieval plan.
    include_references : bool
        Whether callable-reference evidence is enabled by the retrieval plan.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    """

    root: Path
    top_matches: list[SymbolRow]
    conn: sqlite3.Connection
    include_include_graph: bool
    include_references: bool
    prefix: str | None


@dataclass(frozen=True)
class CandidateScoringRule:
    """
    Declarative weight applied to one extracted candidate-scoring feature.

    Parameters
    ----------
    feature : str
        Name of the numeric feature field on ``CandidateScoreFeatures``.
    weight : int
        Signed contribution multiplier applied to the feature value.
    """

    feature: str
    weight: int


@dataclass(frozen=True)
class CandidateScoreFeatures:
    """
    Deterministic lexical-scoring features for one symbol candidate.

    Parameters
    ----------
    exact_name_match : int
        Whether the normalized query exactly matches the symbol name.
    substring_name_match : int
        Whether the normalized query is a substring of the symbol name when no
        exact match applies.
    name_token_overlap_count : int
        Number of overlapping normalized tokens between the query and symbol
        name.
    module_token_overlap_count : int
        Number of overlapping normalized tokens between the query and module
        name.
    is_function : int
        Whether the candidate is a top-level function.
    is_private : int
        Whether the symbol name starts with an underscore.
    path_bias : int
        Intent-aware location bias derived from the owning file path.
    query_targets_module_as_module : int
        Whether the query explicitly asks for a module and this candidate is a
        module.
    query_targets_module_as_non_module : int
        Whether the query explicitly asks for a module and this candidate is
        not a module.
    module_depth_penalty_count : int
        Depth count used to penalize deeply nested modules.
    exact_target_symbol_match : int
        Whether the candidate symbol matches the extracted identifier-like
        target token.
    exact_raw_query_match : int
        Whether the raw query text exactly matches the symbol name.
    lexical_frequency_count : int
        Count of query tokens contained in the symbol name.
    implementation_module_bonus : int
        Whether the owning module is neither tests nor scripts.
    lowered_module_penalty : int
        Whether the module path contains biased infrastructure terms.
    identifier_exact_match : int
        Whether an identifier query exactly matches the symbol name.
    identifier_module_suffix_match : int
        Whether an identifier query matches the end of the module name.
    multi_term_module_bonus : int
        Whether a multi-term query should lightly favor module candidates.
    strong_token_hit : int
        Whether the candidate name contains at least one strong query token.
    """

    exact_name_match: int
    substring_name_match: int
    name_token_overlap_count: int
    module_token_overlap_count: int
    is_function: int
    is_private: int
    path_bias: int
    query_targets_module_as_module: int
    query_targets_module_as_non_module: int
    module_depth_penalty_count: int
    exact_target_symbol_match: int
    exact_raw_query_match: int
    lexical_frequency_count: int
    implementation_module_bonus: int
    lowered_module_penalty: int
    identifier_exact_match: int
    identifier_module_suffix_match: int
    multi_term_module_bonus: int
    strong_token_hit: int


PRIMARY_SYMBOL_SCORING_RULES: tuple[CandidateScoringRule, ...] = (
    CandidateScoringRule("exact_name_match", 100),
    CandidateScoringRule("substring_name_match", 50),
    CandidateScoringRule("name_token_overlap_count", 10),
    CandidateScoringRule("module_token_overlap_count", 3),
    CandidateScoringRule("is_function", 5),
    CandidateScoringRule("is_private", -20),
    CandidateScoringRule("path_bias", 1),
    CandidateScoringRule("query_targets_module_as_module", 120),
    CandidateScoringRule("query_targets_module_as_non_module", -40),
    CandidateScoringRule("module_depth_penalty_count", -5),
    CandidateScoringRule("exact_target_symbol_match", 10),
    CandidateScoringRule("exact_raw_query_match", 5),
    CandidateScoringRule("lexical_frequency_count", 2),
    CandidateScoringRule("implementation_module_bonus", 2),
    CandidateScoringRule("lowered_module_penalty", -2),
    CandidateScoringRule("identifier_exact_match", 25),
    CandidateScoringRule("identifier_module_suffix_match", 8),
    CandidateScoringRule("multi_term_module_bonus", 1),
)

FALLBACK_SYMBOL_SCORING_RULES: tuple[CandidateScoringRule, ...] = (
    CandidateScoringRule("exact_name_match", 100),
    CandidateScoringRule("substring_name_match", 50),
    CandidateScoringRule("name_token_overlap_count", 10),
    CandidateScoringRule("module_token_overlap_count", 3),
    CandidateScoringRule("is_function", 5),
    CandidateScoringRule("is_private", -20),
    CandidateScoringRule("path_bias", 1),
    CandidateScoringRule("query_targets_module_as_module", 120),
    CandidateScoringRule("query_targets_module_as_non_module", -40),
    CandidateScoringRule("module_depth_penalty_count", -5),
    CandidateScoringRule("identifier_exact_match", 25),
    CandidateScoringRule("identifier_module_suffix_match", 8),
    CandidateScoringRule("multi_term_module_bonus", 1),
)


def _symbol_sort_key(symbol: SymbolRow) -> tuple[str, str, str, int, str]:
    """
    Return a deterministic ascending sort key for a symbol row.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Symbol row to normalize into a sortable key.

    Returns
    -------
    tuple[str, str, str, int, str]
        Deterministic ascending key based on module, name, file, line, and type.
    """
    symbol_type, module_name, name, file_path, lineno = symbol
    return (module_name, name, file_path, lineno, symbol_type)


def _scored_symbol_sort_key(
    item: tuple[float, SymbolRow],
) -> tuple[float, str, str, str, int, str]:
    """
    Return a deterministic sort key for scored symbols.

    Parameters
    ----------
    item : tuple[float, codira.types.SymbolRow]
        Score and symbol pair to normalize.

    Returns
    -------
    tuple[float, str, str, str, int, str]
        Sort key ordering by descending score and ascending symbol identity.
    """
    score, symbol = item
    module_name, name, file_path, lineno, symbol_type = _symbol_sort_key(symbol)
    return (-score, module_name, name, file_path, lineno, symbol_type)


def _dedupe_channel_results(channel: ChannelResults) -> ChannelResults:
    """
    Remove duplicate symbols from a single channel while keeping best rank.

    Parameters
    ----------
    channel : codira.types.ChannelResults
        Ranked results emitted by one retrieval channel.

    Returns
    -------
    codira.types.ChannelResults
        Deduplicated channel results preserving the first occurrence of each
        symbol.
    """
    seen: set[SymbolRow] = set()
    deduped: ChannelResults = []

    for score, symbol in channel:
        if symbol in seen:
            continue
        seen.add(symbol)
        deduped.append((score, symbol))

    return deduped


def _render_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    source: str,
) -> str:
    """
    Render a compact signature string for a class or callable node.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        AST node to render.
    source : str
        Source text used to recover argument and return annotations.

    Returns
    -------
    str
        Compact display signature for the supplied node.
    """
    if isinstance(node, ast.ClassDef):
        return f"{node.name}"

    try:
        params = ast.get_source_segment(source, node.args)
    except ValueError:
        params = None

    if not params:
        arg_names = [arg.arg for arg in node.args.args]
        if node.args.vararg is not None:
            arg_names.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg is not None:
            arg_names.append(f"**{node.args.kwarg.arg}")
        params = ", ".join(arg_names)

    returns = ""
    if node.returns is not None:
        try:
            ret = ast.get_source_segment(source, node.returns)
        except ValueError:
            ret = None
        if ret:
            returns = f" -> {ret}"

    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({params}){returns}"


def _truncate_lines(text: str | None, limit: int) -> str | None:
    """
    Truncate multiline text to a fixed number of lines.

    Parameters
    ----------
    text : str | None
        Text block to truncate.
    limit : int
        Maximum number of lines to retain before appending an ellipsis line.

    Returns
    -------
    str | None
        Truncated text, or ``None`` when the input is empty.
    """
    if not text:
        return None

    lines = text.strip().splitlines()
    if len(lines) <= limit:
        return "\n".join(lines)

    kept = lines[:limit]
    kept.append("...")
    return "\n".join(kept)


def _snippet_from_lines(
    source_lines: list[str], lineno: int, limit: int = SNIPPET_LINE_LIMIT
) -> list[str]:
    """
    Slice a fixed-size snippet from raw source lines.

    Parameters
    ----------
    source_lines : list[str]
        Source file split into lines.
    lineno : int
        One-based line number at which the snippet should start.
    limit : int, optional
        Maximum number of lines to return.

    Returns
    -------
    list[str]
        Right-stripped source lines for the requested slice.
    """
    start = max(lineno - 1, 0)
    end = min(start + limit, len(source_lines))
    return [line.rstrip() for line in source_lines[start:end]]


def _normalize_snippet_lines(lines: list[str], limit: int) -> list[str]:
    """
    Normalize snippet lines for readable deterministic display.

    Parameters
    ----------
    lines : list[str]
        Raw snippet lines.
    limit : int
        Maximum number of normalized lines to retain.

    Returns
    -------
    list[str]
        Snippet lines with trailing whitespace removed, edge blanks trimmed,
        and repeated blank lines collapsed.
    """
    normalized: list[str] = []
    previous_blank = False

    for raw_line in lines:
        line = raw_line.rstrip()
        is_blank = line == ""

        if is_blank and previous_blank:
            continue

        normalized.append(line)
        previous_blank = is_blank

    while normalized and normalized[0] == "":
        normalized.pop(0)

    while normalized and normalized[-1] == "":
        normalized.pop()

    return normalized[:limit]


def _snippet_from_node(
    node: ast.AST,
    source_lines: list[str],
    limit: int = SNIPPET_LINE_LIMIT,
) -> list[str]:
    """
    Extract a compact snippet for a node using AST positions.

    Parameters
    ----------
    node : ast.AST
        AST node whose source snippet should be extracted.
    source_lines : list[str]
        Source file split into lines.
    limit : int, optional
        Maximum number of snippet lines to retain.

    Returns
    -------
    list[str]
        Normalized snippet lines for the node.

    Notes
    -----
    Decorators are included when present. Leading docstring blocks are removed
    from the snippet so the reader sees executable structure first.
    """
    # Determine start (include decorators if present)
    start = getattr(node, "lineno", 1) - 1

    # --- include decorators if present ---
    if (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.decorator_list
    ):
        with contextlib.suppress(AttributeError, ValueError):
            start = min(d.lineno for d in node.decorator_list) - 1

    # Determine end (best-effort)
    end = getattr(node, "end_lineno", None)
    if end is None:
        end = getattr(node, "lineno", 1)

    # Slice and truncate
    snippet = source_lines[start:end]

    # --- remove docstring if present ---
    body = getattr(node, "body", None)
    if body:
        doc = ast.get_docstring(
            cast(
                "ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Module",
                node,
            ),
            clean=False,
        )
        if doc is not None and isinstance(body[0], ast.Expr):
            doc_node = body[0]

            # absolute positions
            doc_start = doc_node.lineno - 1
            doc_end = getattr(doc_node, "end_lineno", doc_start + 1)

            # snippet base offset
            snippet_start = start

            # convert to snippet-local indices
            local_start = doc_start - snippet_start
            local_end = doc_end - snippet_start

            snippet = [
                line
                for i, line in enumerate(snippet)
                if not (local_start <= i < local_end)
            ]

    # --- truncate ---
    return _normalize_snippet_lines(snippet, limit)


def _extract_code_context(
    root: Path,
    symbol: SymbolRow,
    cache: dict[Path, tuple[str, list[str], ast.Module]],
) -> CodeContext:
    """
    Extract signature, docstring, and snippet data for a symbol.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to resolve file paths.
    symbol : codira.types.SymbolRow
        Indexed symbol row to expand.
    cache : dict[pathlib.Path, tuple[str, list[str], ast.Module]]
        Parsed-file cache shared across multiple lookups.

    Returns
    -------
    codira.types.CodeContext
        Signature, truncated docstring, and code snippet for the symbol.
    """
    symbol_type, _module_name, name, file_path, lineno = symbol
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path

    if path in cache:
        source, source_lines, tree = cache[path]
    else:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return (None, None, [])

        source_lines = source.splitlines()

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return (None, None, _snippet_from_lines(source_lines, lineno))

        cache[path] = (source, source_lines, tree)

    if symbol_type == "module":
        module_doc = ast.get_docstring(tree, clean=True)
        snippet = _snippet_from_lines(source_lines, lineno)
        return (
            None,
            _truncate_lines(module_doc, DOCSTRING_PREVIEW_LINE_LIMIT),
            snippet,
        )

    # --- CLASS MATCH ---
    if symbol_type == "class":
        class_candidates: list[ast.ClassDef] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                class_candidates.append(node)

        if class_candidates:
            node = min(class_candidates, key=lambda n: abs(n.lineno - lineno))
            signature = _render_signature(node, source)
            docstring = ast.get_docstring(node, clean=True)
            snippet = _snippet_from_node(node, source_lines)
            return (
                signature,
                _truncate_lines(docstring, DOCSTRING_PREVIEW_LINE_LIMIT),
                snippet,
            )

    # --- FUNCTION MATCH ---
    if symbol_type == "function":
        func_candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name
            ):
                func_candidates.append(node)

        if func_candidates:
            node = min(func_candidates, key=lambda n: abs(n.lineno - lineno))
            signature = _render_signature(node, source)
            docstring = ast.get_docstring(node, clean=True)
            snippet = _snippet_from_node(node, source_lines)
            return (
                signature,
                _truncate_lines(docstring, DOCSTRING_PREVIEW_LINE_LIMIT),
                snippet,
            )

    # --- METHOD MATCH ---
    if symbol_type == "method":
        method_candidates: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if (
                        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name == name
                    ):
                        method_candidates.append(child)

        if method_candidates:
            node = min(method_candidates, key=lambda n: abs(n.lineno - lineno))
            signature = _render_signature(node, source)
            docstring = ast.get_docstring(node, clean=True)
            snippet = _snippet_from_node(node, source_lines)
            return (
                signature,
                _truncate_lines(docstring, DOCSTRING_PREVIEW_LINE_LIMIT),
                snippet,
            )

    # --- FALLBACK ---
    return (None, None, _snippet_from_lines(source_lines, lineno))


def _symbols_in_module(
    root: Path,
    module: str,
    *,
    prefix: str | None = None,
) -> list[SymbolRow]:
    """
    Retrieve indexed symbols belonging to a module.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    module : str
        Dotted module name to expand.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.

    Returns
    -------
    list[codira.types.SymbolRow]
        Up to twenty indexed symbols from the requested module.
    """
    backend = active_index_backend()
    return backend.list_symbols_in_module(
        root,
        module,
        prefix=prefix,
        limit=20,
    )


def _find_references(
    root: Path,
    name: str,
    project_files: list[Path],
    file_cache: dict[Path, list[str]] | None = None,
) -> list[ReferenceRow]:
    """
    Find references to a symbol name across indexed Python files.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize file paths.
    name : str
        Symbol name to search for.
    project_files : list[pathlib.Path]
        Indexed project files to scan.
    file_cache : dict[pathlib.Path, list[str]] | None, optional
        Optional in-memory file cache reused across scans.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Reference locations as ``(file_path, lineno)`` tuples.

    Notes
    -----
    The function relies on the indexing phase to define the set of
    project files, ensuring consistency between indexing and querying. It uses
    simple string containment, skips import statements, and caps the total
    number of returned hits.
    """
    results: list[ReferenceRow] = []
    if file_cache is None:
        file_cache = {}

    for path in project_files:
        if path in file_cache:
            lines = file_cache[path]
        else:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            file_cache[path] = lines
        file_path = str(path)

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            # --- FILTER: skip imports ---
            if stripped.startswith(("import ", "from ")):
                continue

            # simple containment check
            if name not in line:
                continue

            results.append((file_path, lineno))

            # hard cap (global)
            if len(results) >= 50:
                return results

    return results


def _tokenize(text: str) -> set[str]:
    """
    Tokenize text into lowercased alphanumeric and underscore fragments.

    Parameters
    ----------
    text : str
        Input text to split.

    Returns
    -------
    set[str]
        Unique normalized tokens extracted from the input.
    """
    parts = re.split(r"[^A-Za-z0-9_]+", text.lower())
    tokens: set[str] = set()

    for part in parts:
        if not part:
            continue

        tokens.add(part)
        for sub in part.split("_"):
            if sub:
                tokens.add(sub)

    return tokens


def _classify_file_role(file_path: str, module_name: str) -> FileRole:
    """
    Classify one indexed file into a deterministic retrieval role.

    Parameters
    ----------
    file_path : str
        Indexed file path for the candidate symbol.
    module_name : str
        Indexed module name owning the candidate symbol.

    Returns
    -------
    {"implementation", "interface", "test", "tooling", "other"}
        Deterministic file role used by retrieval scoring.
    """
    path_obj = Path(file_path)
    lowered_parts = {part.lower() for part in path_obj.parts}
    lowered_name = path_obj.name.lower()
    lowered_module = module_name.lower()

    if (
        "tests" in lowered_parts
        or lowered_name.startswith("test_")
        or lowered_module.startswith("tests.")
    ):
        return "test"

    if lowered_module.startswith("scripts.") or any(
        part in lowered_parts for part in {"scripts", "tools", "bin"}
    ):
        return "tooling"

    if path_obj.suffix == ".h":
        return "interface"

    if path_obj.suffix in {".c", ".py"}:
        return "implementation"

    return "other"


def _file_role_bias(role: FileRole, intent: QueryIntent | None = None) -> int:
    """
    Return the retrieval bias associated with one file role.

    Parameters
    ----------
    role : {"implementation", "interface", "test", "tooling", "other"}
        Deterministic file role for the candidate symbol.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to flip test or tooling preferences when explicit.

    Returns
    -------
    int
        Small deterministic additive ranking bias.
    """
    if role == "implementation":
        return (
            1 if intent and (intent.is_test_related or intent.is_script_related) else 3
        )

    if role == "interface":
        return 2

    if role == "test":
        return 4 if intent and intent.is_test_related else -4

    if role == "tooling":
        return 4 if intent and intent.is_script_related else -5

    return 0


def _path_bias(
    file_path: str,
    module_name: str,
    *,
    intent: QueryIntent | None = None,
) -> int:
    """
    Lightweight ranking bias based on file location.

    Parameters
    ----------
    file_path : str
        Indexed file path for the candidate symbol.
    module_name : str
        Indexed module name owning the candidate symbol.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to flip test and tooling preferences when explicit.

    Returns
    -------
    int
        Small additive score bias based on the file location.

    Notes
    -----
    The bias prefers source files over scripts and tests without suppressing
    those results entirely.
    """
    role = _classify_file_role(file_path, module_name)
    return _file_role_bias(role, intent)


def _score_match(
    query_tokens: list[str],
    symbol: SymbolRow,
    *,
    intent: QueryIntent | None = None,
) -> int:
    """
    Score a symbol candidate against tokenized query text.

    Parameters
    ----------
    query_tokens : list[str]
        Normalized query tokens.
    symbol : codira.types.SymbolRow
        Candidate symbol row to score.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias ranking toward the user's apparent goal.

    Returns
    -------
    int
        Deterministic relevance score for the candidate.
    """
    features = _extract_candidate_score_features(
        query_tokens,
        symbol,
        intent=intent,
    )
    return _apply_scoring_rules(features, PRIMARY_SYMBOL_SCORING_RULES)


def _extract_target_symbol(query_tokens: list[str]) -> str | None:
    """
    Extract the strongest identifier-like token from a query.

    Parameters
    ----------
    query_tokens : list[str]
        Normalized query tokens.

    Returns
    -------
    str | None
        Longest identifier-like token when present.
    """
    for token in sorted(query_tokens, key=len, reverse=True):
        if "_" in token or token.isidentifier():
            return token
    return None


def _normalized_strong_query_tokens(query_tokens: list[str]) -> list[str]:
    """
    Expand strong query tokens into a normalized gating token list.

    Parameters
    ----------
    query_tokens : list[str]
        Normalized query tokens.

    Returns
    -------
    list[str]
        Strong tokens plus underscore-separated fragments in stable order.
    """
    strong_tokens = [token for token in query_tokens if len(token) >= 4]
    normalized_tokens: list[str] = []
    for token in strong_tokens:
        normalized_tokens.append(token)
        if "_" in token:
            normalized_tokens.extend(token.split("_"))
    return normalized_tokens


def _extract_candidate_score_features(
    query_tokens: list[str],
    symbol: SymbolRow,
    *,
    intent: QueryIntent | None = None,
    raw_query: str | None = None,
    target_symbol: str | None = None,
) -> CandidateScoreFeatures:
    """
    Extract deterministic lexical-scoring features for one symbol candidate.

    Parameters
    ----------
    query_tokens : list[str]
        Normalized query tokens.
    symbol : codira.types.SymbolRow
        Candidate symbol row to score.
    intent : codira.query.classifier.QueryIntent | None, optional
        Structured query classification.
    raw_query : str | None, optional
        Unsanitized query text used for exact-name bonuses.
    target_symbol : str | None, optional
        Identifier-like query token singled out for exact-name boosts.

    Returns
    -------
    CandidateScoreFeatures
        Extracted numeric features consumed by the scoring rule tables.
    """
    symbol_type, module_name, name, file_path, _lineno = symbol
    normalized_query = " ".join(query_tokens)
    symbol_name = name
    module_tokens = set(_tokenize(module_name))
    name_tokens = set(_tokenize(symbol_name))
    normalized_strong_tokens = _normalized_strong_query_tokens(query_tokens)

    return CandidateScoreFeatures(
        exact_name_match=int(normalized_query == symbol_name),
        substring_name_match=int(
            normalized_query != symbol_name and bool(normalized_query in symbol_name)
        ),
        name_token_overlap_count=len(set(query_tokens) & name_tokens),
        module_token_overlap_count=len(set(query_tokens) & module_tokens),
        is_function=int(symbol_type == "function"),
        is_private=int(symbol_name.startswith("_")),
        path_bias=_path_bias(file_path, module_name, intent=intent),
        query_targets_module_as_module=int(
            "module" in query_tokens and symbol_type == "module"
        ),
        query_targets_module_as_non_module=int(
            "module" in query_tokens and symbol_type != "module"
        ),
        module_depth_penalty_count=(
            module_name.count(".") if symbol_type == "module" else 0
        ),
        exact_target_symbol_match=int(
            target_symbol is not None and symbol_name == target_symbol
        ),
        exact_raw_query_match=int(raw_query is not None and symbol_name == raw_query),
        lexical_frequency_count=sum(
            1 for token in query_tokens if token in symbol_name.lower()
        ),
        implementation_module_bonus=int(
            not module_name.startswith("tests.")
            and not module_name.startswith("scripts.")
        ),
        lowered_module_penalty=int(
            any(x in module_name.lower() for x in ("cli", "scanner", "storage"))
        ),
        identifier_exact_match=int(
            bool(intent and intent.is_identifier_query and symbol_name == intent.raw)
        ),
        identifier_module_suffix_match=int(
            bool(
                intent
                and intent.is_identifier_query
                and module_name.endswith(intent.raw)
                and symbol_name != intent.raw
            )
        ),
        multi_term_module_bonus=int(
            bool(intent and intent.is_multi_term and symbol_type == "module")
        ),
        strong_token_hit=int(
            any(token in _tokenize(symbol_name) for token in normalized_strong_tokens)
        ),
    )


def _apply_scoring_rules(
    features: CandidateScoreFeatures,
    rules: tuple[CandidateScoringRule, ...],
) -> int:
    """
    Apply a declarative rule table to extracted candidate-scoring features.

    Parameters
    ----------
    features : CandidateScoreFeatures
        Extracted feature values for one candidate symbol.
    rules : tuple[CandidateScoringRule, ...]
        Ordered score rules to apply.

    Returns
    -------
    int
        Total deterministic score contribution from the supplied rules.
    """
    return sum(getattr(features, rule.feature) * rule.weight for rule in rules)


def _format_symbol(symbol: SymbolRow, *, include_path: bool) -> str:
    """
    Format a symbol row for human-readable output.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Symbol row to render.
    include_path : bool
        Whether to append a file path suffix.

    Returns
    -------
    str
        Single-line textual representation of the symbol.
    """
    symbol_type, module_name, name, file_path, lineno = symbol

    if symbol_type == "module":
        head = f"{symbol_type}: {module_name}:{lineno}"
    else:
        head = f"{symbol_type}: {module_name}.{name}:{lineno}"

    if include_path:
        try:
            rel_path = str(Path(file_path).relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(file_path)
        return f"{head} ({rel_path})"
    return head


def _format_enriched_symbol(
    root: Path,
    symbol: SymbolRow,
    cache: dict[Path, tuple[str, list[str], ast.Module]],
) -> list[str]:
    """
    Format a symbol with location, snippet, and docstring details.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    symbol : codira.types.SymbolRow
        Symbol row to render.
    cache : dict[pathlib.Path, tuple[str, list[str], ast.Module]]
        Parsed-file cache shared across multiple symbols.

    Returns
    -------
    list[str]
        Multi-line textual block describing the symbol.
    """
    symbol_type, module_name, name, file_path, lineno = symbol
    signature, docstring, snippet = _extract_code_context(root, symbol, cache)

    lines: list[str] = []

    if symbol_type == "module":
        lines.append(f"module {module_name}")
    elif signature:
        lines.append(f"{symbol_type} {signature}")
    else:
        lines.append(f"{symbol_type} {name} in {module_name}")

    try:
        rel_path = str(Path(file_path).relative_to(root))
    except ValueError:
        rel_path = str(file_path)

    lines.append(f"  File: {rel_path}")
    lines.append(f"  Line: {lineno}")

    if snippet:
        lines.append("  Snippet:")
        for line in snippet:
            lines.append(f"    {line}")

    if docstring:
        lines.append("  Docstring:")
        doc_lines = docstring.splitlines()

        for line in doc_lines[:DISPLAY_DOCSTRING_LINE_LIMIT]:
            lines.append(f"    {line}")

        if len(doc_lines) > DISPLAY_DOCSTRING_LINE_LIMIT:
            lines.append("    [...]")

    return lines


def _retrieve_symbol_candidates(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    prefix: str | None,
) -> ChannelResults:
    """
    Retrieve and score symbol-channel candidates for a query.

    Parameters
    ----------
    root : pathlib.Path
        Root directory of the indexed repository.
    query : str
        User query string.
    conn : sqlite3.Connection
        Active database connection.
    intent : QueryIntent
        Structured classification of the query.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    list[tuple[float, SymbolRow]]
        Ranked candidate symbols with scores sorted by descending score.

    Notes
    -----
    This phase applies deterministic scoring only. It does not perform
    final deduplication or pruning.
    """
    matches = find_symbol(root, query, prefix=prefix, conn=conn)
    query_tokens = sorted(_tokenize(query))

    candidate_map: dict[SymbolRow, None] = {match: None for match in matches}

    search_terms = sorted({token for token in query_tokens if len(token) >= 4})
    prefix_sql, prefix_params = prefix_clause(prefix, "f.path")

    for term in search_terms:
        rows = conn.execute(
            f"""
            SELECT s.type, s.module_name, s.name, f.path, s.lineno
            FROM symbol_index s
            JOIN files f
              ON s.file_id = f.id
            WHERE (s.name = ?
               OR s.name LIKE ?
               OR s.module_name LIKE ?)
            {prefix_sql}
            ORDER BY s.type, s.module_name, f.path, s.lineno
            LIMIT ?
            """,
            (
                term,
                f"%{term}%",
                f"%{term}%",
                *prefix_params,
                SYMBOL_TERM_MATCH_LIMIT,
            ),
        ).fetchall()

        for row in rows:
            candidate = (
                str(row[0]),
                str(row[1]),
                str(row[2]),
                str(row[3]),
                int(row[4]),
            )
            candidate_map[candidate] = None

    if candidate_map:
        all_candidates = sorted(
            candidate_map,
            key=lambda symbol: (symbol[1], symbol[2], symbol[3], symbol[4]),
        )
    else:
        rows = conn.execute(
            f"""
            SELECT s.type, s.module_name, s.name, f.path, s.lineno
            FROM symbol_index s
            JOIN files f
              ON s.file_id = f.id
            WHERE 1 = 1
            {prefix_sql}
            ORDER BY s.module_name, s.name, f.path, s.lineno
            LIMIT ?
            """,
            (*prefix_params, SYMBOL_FALLBACK_SCAN_LIMIT),
        ).fetchall()
        all_candidates = [
            (str(t), str(m), str(n), str(f), int(lin)) for t, m, n, f, lin in rows
        ]

    target_symbol = _extract_target_symbol(query_tokens)
    scored: list[tuple[float, SymbolRow]] = []

    for candidate in all_candidates:
        features = _extract_candidate_score_features(
            query_tokens,
            candidate,
            intent=intent,
            raw_query=query,
            target_symbol=target_symbol,
        )
        if not features.strong_token_hit:
            continue
        score = _apply_scoring_rules(features, PRIMARY_SYMBOL_SCORING_RULES)
        if score >= _MIN_SCORE:
            scored.append((float(score), candidate))

    scored.sort(key=_scored_symbol_sort_key)

    if not scored:
        fallback_scored: list[tuple[float, SymbolRow]] = []

        for candidate in all_candidates:
            features = _extract_candidate_score_features(
                query_tokens,
                candidate,
                intent=intent,
            )
            score = _apply_scoring_rules(features, FALLBACK_SYMBOL_SCORING_RULES)
            fallback_scored.append((float(score), candidate))

        fallback_scored.sort(key=_scored_symbol_sort_key)
        return fallback_scored

    return scored


def _retrieve_test_candidates(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    prefix: str | None,
) -> ChannelResults:
    """
    Retrieve candidates for the test channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    codira.types.ChannelResults
        Empty channel results. Test-specific retrieval is not implemented.
    """
    del root, query, conn, intent, prefix
    return []


def _retrieve_script_candidates(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    prefix: str | None,
) -> ChannelResults:
    """
    Retrieve candidates for the script channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    codira.types.ChannelResults
        Empty channel results. Script-specific retrieval is not implemented.
    """
    del root, query, conn, intent, prefix
    return []


def _merge_ranked_channels(
    channels: list[ChannelBundle],
    *,
    intent: QueryIntent | None = None,
) -> list[SymbolRow]:
    """
    Merge ranked channels into a single ordered symbol list.

    Parameters
    ----------
    channels : list[codira.types.ChannelBundle]
        Ranked channel results to combine.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias merged ranking decisions.

    Returns
    -------
    list[codira.types.SymbolRow]
        Top merged symbol rows.
    """
    return _merge_ranked_channel_bundles(channels, intent=intent)


def _merge_ranked_channel_bundles_explain(
    bundles: list[ChannelBundle],
    *,
    intent: QueryIntent | None = None,
) -> tuple[list[SymbolRow], MergeDiagnostics]:
    """
    Merge channel bundles while preserving per-channel score provenance.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles to combine.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias merged ranking decisions.

    Returns
    -------
    tuple[
        list[codira.types.SymbolRow],
        codira.query.context.MergeDiagnostics,
    ]
        Top merged symbols and a provenance map keyed by symbol.
    """
    ranked, provenance = _rank_merged_symbols_with_provenance(bundles, intent=intent)
    top_symbols = _diversify_merged_symbols([symbol for symbol, _ in ranked])

    return top_symbols, provenance


def _merge_ranked_channel_bundles(
    bundles: list[ChannelBundle],
    *,
    intent: QueryIntent | None = None,
) -> list[SymbolRow]:
    """
    Merge ranked channel bundles without returning provenance details.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles to combine.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias merged ranking decisions.

    Returns
    -------
    list[codira.types.SymbolRow]
        Top merged symbol rows.
    """
    top_symbols, _ = _merge_ranked_channel_bundles_explain(bundles, intent=intent)
    return top_symbols


def _rank_merged_symbols_with_provenance(
    bundles: list[ChannelBundle],
    *,
    intent: QueryIntent | None = None,
) -> tuple[list[tuple[SymbolRow, float]], MergeDiagnostics]:
    """
    Rank merged symbols and retain per-channel score provenance.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles to combine.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias merged ranking decisions.

    Returns
    -------
    tuple[
        list[tuple[codira.types.SymbolRow, float]],
        codira.query.context.MergeDiagnostics,
    ]
        Ranked merged symbols with their aggregate score and channel provenance.
    """
    channel_names = [channel_name for channel_name, _channel in bundles]
    producers = _channel_retrieval_producers(channel_names)
    signals, _diagnostics = _collect_retrieval_signals(bundles, producers=producers)
    return _rank_signals_with_provenance(signals, intent=intent)


def _rank_signals_with_provenance(
    signals: list[RetrievalSignal],
    *,
    intent: QueryIntent | None = None,
) -> tuple[list[tuple[SymbolRow, float]], MergeDiagnostics]:
    """
    Rank merged symbols from normalized retrieval signals.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized retrieval signals contributing to ranking.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to bias merged ranking decisions.

    Returns
    -------
    tuple[
        list[tuple[codira.types.SymbolRow, float]],
        codira.query.context.MergeDiagnostics,
    ]
        Ranked merged symbols with their aggregate score and signal-derived
        provenance.
    """
    weights = _channel_weights()
    merged_rrf: dict[SymbolRow, float] = {}
    channel_scores: dict[SymbolRow, dict[str, float]] = {}
    family_scores_by_symbol: dict[SymbolRow, dict[str, float]] = {}

    for signal in sorted(signals, key=signal_sort_key):
        symbol = signal.target
        channel_name = signal.channel_name
        if channel_name is None:
            continue

        weight = weights.get(channel_name, 1.0)
        strength = signal.strength if signal.strength is not None else 0.0
        weighted_score = strength * weight
        symbol_channel_scores = channel_scores.setdefault(symbol, {})
        symbol_channel_scores[channel_name] = weighted_score

        symbol_family_scores = family_scores_by_symbol.setdefault(symbol, {})
        symbol_family_scores[signal.family] = (
            symbol_family_scores.get(signal.family, 0.0) + weighted_score
        )

        if signal.rank is None:
            continue

        merged_rrf[symbol] = merged_rrf.get(symbol, 0.0) + (
            weight * (1.0 / float(signal.rank))
        )

    diagnostics: MergeDiagnostics = {}
    ranked_with_scores: list[tuple[SymbolRow, float]] = []

    for symbol, rrf_score in merged_rrf.items():
        symbol_channel_scores = channel_scores.get(symbol, {})
        family_scores = family_scores_by_symbol.get(symbol, {})
        role = _classify_file_role(symbol[3], symbol[1])
        role_bias = _file_role_bias(role, intent)
        evidence_bonus = _merge_evidence_bonus(family_scores)
        role_bonus = float(role_bias) / 4.0
        merge_score = rrf_score + evidence_bonus + role_bonus
        winner = max(
            sorted(symbol_channel_scores.items()),
            key=lambda item: item[1],
        )[0]
        diagnostics[symbol] = {
            "channels": dict(
                sorted(
                    symbol_channel_scores.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
            "families": dict(
                sorted(
                    family_scores.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ),
            "rrf_score": rrf_score,
            "evidence_bonus": evidence_bonus,
            "role_bonus": role_bonus,
            "merge_score": merge_score,
            "winner": winner,
        }
        ranked_with_scores.append((symbol, merge_score))

    ranked = sorted(
        ranked_with_scores,
        key=lambda item: (-item[1], *_symbol_sort_key(item[0])),
    )
    return ranked, diagnostics


def _diversify_merged_symbols(ranked_symbols: list[SymbolRow]) -> list[SymbolRow]:
    """
    Apply deterministic file and role caps to merged ranked symbols.

    Parameters
    ----------
    ranked_symbols : list[codira.types.SymbolRow]
        Symbols already ordered by merged ranking score.

    Returns
    -------
    list[codira.types.SymbolRow]
        Diversified top symbols capped by file and role before truncation.
    """
    selected, _diagnostics = _diversify_merged_symbols_explain(ranked_symbols)
    return selected


def _diversify_merged_symbols_explain(
    ranked_symbols: list[SymbolRow],
) -> tuple[list[SymbolRow], DiversityDiagnostics]:
    """
    Diversify merged symbols while collecting deterministic diagnostics.

    Parameters
    ----------
    ranked_symbols : list[codira.types.SymbolRow]
        Symbols already ordered by merged ranking score.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], codira.query.context.DiversityDiagnostics]
        Diversified symbols plus selected and deferred diagnostic entries.
    """
    selected: list[SymbolRow] = []
    seen_files: dict[str, int] = {}
    role_counts: dict[FileRole, int] = {}
    language_counts: dict[str, int] = {}
    available_languages = {
        _classify_file_language(symbol[3]) for symbol in ranked_symbols
    }
    deferred: list[tuple[SymbolRow, DeferralReason]] = []
    selected_entries: list[DiversityEntry] = []
    deferred_entries: list[DiversityEntry] = []

    def _diagnostic_entry(
        symbol: SymbolRow,
        *,
        role: FileRole,
        language: str,
        selection_stage: SelectionStage | None = None,
        reason: DeferralReason | None = None,
    ) -> DiversityEntry:
        symbol_type, module_name, name, file_path, lineno = symbol
        entry: DiversityEntry = {
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "file": file_path,
            "lineno": lineno,
            "role": role,
            "language": language,
        }
        if selection_stage is not None:
            entry["selection_stage"] = selection_stage
        if reason is not None:
            entry["reason"] = reason
        return entry

    def _try_append(symbol: SymbolRow, *, selection_stage: SelectionStage) -> bool:
        file_path = symbol[3]
        module_name = symbol[1]
        role = _classify_file_role(file_path, module_name)
        language = _classify_file_language(file_path)

        if seen_files.get(file_path, 0) >= MERGE_MAX_PER_FILE:
            if selection_stage == "primary":
                deferred.append((symbol, "file_cap"))
            return False

        if (
            selection_stage == "primary"
            and role_counts.get(role, 0) >= MERGE_ROLE_CAPS[role]
        ):
            deferred.append((symbol, "role_cap"))
            return False

        if (
            selection_stage == "primary"
            and len(available_languages) > 1
            and language_counts.get(language, 0) >= MERGE_LANGUAGE_CAPS.get(language, 1)
        ):
            deferred.append((symbol, "language_cap"))
            return False

        selected.append(symbol)
        seen_files[file_path] = seen_files.get(file_path, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
        language_counts[language] = language_counts.get(language, 0) + 1
        selected_entries.append(
            _diagnostic_entry(
                symbol,
                role=role,
                language=language,
                selection_stage=selection_stage,
            )
        )
        return True

    for symbol in ranked_symbols:
        if len(selected) >= MERGE_RESULT_LIMIT:
            break
        _try_append(symbol, selection_stage="primary")

    for symbol, reason in deferred:
        role = _classify_file_role(symbol[3], symbol[1])
        language = _classify_file_language(symbol[3])
        deferred_entries.append(
            _diagnostic_entry(
                symbol,
                role=role,
                language=language,
                reason=reason,
            )
        )

    for symbol, _reason in deferred:
        if len(selected) >= MERGE_RESULT_LIMIT:
            break
        _try_append(symbol, selection_stage="deferred")

    diagnostics: DiversityDiagnostics = {
        "selected": selected_entries,
        "deferred": deferred_entries,
    }
    return selected, diagnostics


def _channel_weights() -> dict[ChannelName, float]:
    """
    Return channel weights used during rank fusion.

    Parameters
    ----------
    None

    Returns
    -------
    dict[codira.types.ChannelName, float]
        Weight per retrieval channel.
    """
    return dict(CHANNEL_WEIGHTS)


def _channel_evidence_family(channel_name: ChannelName) -> str:
    """
    Map one retrieval channel to a stable evidence family label.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Retrieval channel contributing to the merged ranking.

    Returns
    -------
    str
        Stable evidence-family label used in explain diagnostics.
    """
    if channel_name == "symbol":
        return "lexical"
    if channel_name in {"embedding", "semantic"}:
        return "semantic"
    return "task"


def _classify_file_language(file_path: str) -> str:
    """
    Classify one indexed file into a deterministic language family.

    Parameters
    ----------
    file_path : str
        Indexed file path for the candidate symbol.

    Returns
    -------
    str
        Stable language-family label used by diversity selection.
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".c", ".h"}:
        return "c"
    return "other"


def _include_target_module_name(target_name: str, kind: str) -> str | None:
    """
    Resolve a local include target path back to an indexed module name.

    Parameters
    ----------
    target_name : str
        Include target as stored in the imports table.
    kind : str
        Import-like kind recorded for the include artifact.

    Returns
    -------
    str | None
        Indexed module name for local includes, or ``None`` when the target
        should not resolve into the include graph.
    """
    if kind != "include_local":
        return None

    target_path = Path(target_name)
    if target_path.suffix not in {".h", ".c"}:
        return None

    return ".".join(target_path.with_suffix("").parts)


def _merge_evidence_bonus(family_scores: dict[str, float]) -> float:
    """
    Return a deterministic bonus for multi-family evidence support.

    Parameters
    ----------
    family_scores : dict[str, float]
        Aggregate weighted evidence scores keyed by evidence family.

    Returns
    -------
    float
        Small additive bonus rewarding symbols supported by multiple
        independent evidence families.
    """
    family_count = len(family_scores)
    if family_count <= 1:
        return 0.0
    return float(family_count - 1) * MERGE_CROSS_FAMILY_BONUS


def _channel_order() -> list[ChannelName]:
    """
    Return the default channel evaluation order.

    Parameters
    ----------
    None

    Returns
    -------
    list[codira.types.ChannelName]
        Channel names in evaluation order.
    """
    return ["symbol", "embedding", "semantic", "test", "script"]


def _build_channel_bundles(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    plan: RetrievalPlan,
    prefix: str | None,
) -> list[ChannelBundle]:
    """
    Execute the enabled retrieval channels for a query.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan derived from the query intent.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    list[codira.types.ChannelBundle]
        Channel names paired with their ranked results.
    """
    channel_fns = _get_channel_functions(plan)

    return [(name, fn(root, query, conn, intent, prefix)) for name, fn in channel_fns]


def _channel_retrieval_producers(
    ordered_channels: list[ChannelName],
) -> list[QueryProducerSpec]:
    """
    Build query producer specs for channel-only aggregation paths.

    Parameters
    ----------
    ordered_channels : list[codira.types.ChannelName]
        Channel order active for the query.

    Returns
    -------
    list[codira.query.producers.QueryProducerSpec]
        Channel producers without enrichment-specific entries.
    """
    return channel_producer_specs(ordered_channels)


def _producer_diagnostics(
    producers: list[QueryProducerSpec],
) -> list[ProducerDiagnosticsEntry]:
    """
    Render explain diagnostics for one list of retrieval producers.

    Parameters
    ----------
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers for the current runtime.

    Returns
    -------
    list[dict[str, object]]
        Deterministic diagnostics for explain JSON and text rendering.
    """
    diagnostics: list[ProducerDiagnosticsEntry] = []

    for producer in producers:
        declared = producer.capabilities
        known, unknown = split_declared_retrieval_capabilities(declared)
        diagnostics.append(
            {
                "producer_name": producer.producer_name,
                "producer_version": producer.producer_version,
                "capability_version": producer.capability_version,
                "source_kind": producer.source_kind,
                "source_name": producer.source_name,
                "declared_capabilities": list(declared),
                "known_capabilities": list(known),
                "unknown_capabilities": list(unknown),
            }
        )

    return diagnostics


def _signal_kind_for_channel(channel_name: ChannelName) -> str:
    """
    Return the normalized signal kind for one legacy retrieval channel.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Stable signal kind derived from the query channel.
    """
    if channel_name == "symbol":
        return "exact_symbol"
    if channel_name == "embedding":
        return "embedding_similarity"
    return "text_match"


def _signal_family_for_channel(channel_name: ChannelName) -> str:
    """
    Return the normalized signal family for one legacy retrieval channel.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Stable signal family derived from the query channel.
    """
    if channel_name == "symbol":
        return "lexical"
    if channel_name in {"embedding", "semantic"}:
        return "semantic"
    return "task"


def _signal_capability_for_channel(channel_name: ChannelName) -> str:
    """
    Return the primary capability that explains one query channel signal.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Legacy retrieval channel name.

    Returns
    -------
    str
        Capability name attributed to signals emitted by the channel.
    """
    if channel_name == "symbol":
        return "symbol_lookup"
    if channel_name == "embedding":
        return "embedding_similarity"
    if channel_name == "semantic":
        return "semantic_text"
    return "task_specialization"


def _signals_from_channel_bundles(
    bundles: list[ChannelBundle],
    *,
    producers: list[QueryProducerSpec],
) -> list[RetrievalSignal]:
    """
    Convert current channel results into normalized retrieval signals.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles for the current query.
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers synthesized for the same query.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ordered signals representing the current channel
        evidence without changing merge behavior.
    """
    producer_by_channel = {
        producer.source_name: producer
        for producer in producers
        if producer.source_kind == "channel"
    }
    signals: list[RetrievalSignal] = []

    for channel_name, channel in sorted(bundles, key=lambda item: item[0]):
        producer = producer_by_channel.get(channel_name)
        if producer is None:
            continue

        capability_name = _signal_capability_for_channel(channel_name)

        for rank, (strength, symbol) in enumerate(
            _dedupe_channel_results(channel), start=1
        ):
            signals.append(
                RetrievalSignal(
                    kind=cast(
                        "Literal['exact_symbol', 'text_match', 'embedding_similarity', 'relation', 'proximity', 'repeated_evidence']",
                        _signal_kind_for_channel(channel_name),
                    ),
                    family=cast(
                        "Literal['lexical', 'semantic', 'task', 'graph', 'issue']",
                        _signal_family_for_channel(channel_name),
                    ),
                    target=symbol,
                    producer_name=producer.producer_name,
                    producer_version=producer.producer_version,
                    capability_name=capability_name,
                    capability_version=producer.capability_version,
                    channel_name=channel_name,
                    rank=rank,
                    strength=strength,
                )
            )

    return sorted(signals, key=signal_sort_key)


def _signals_from_channel_producer(
    producer: QueryProducerSpec,
    *,
    channel: ChannelResults,
) -> list[RetrievalSignal]:
    """
    Convert one query channel producer into normalized retrieval signals.

    Parameters
    ----------
    producer : codira.query.producers.QueryProducerSpec
        Query-layer producer for one retrieval channel.
    channel : codira.types.ChannelResults
        Ranked results emitted by the producer's channel.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ordered signals contributed by the producer.
    """
    channel_name = producer.source_name
    capability_name = _signal_capability_for_channel(channel_name)
    signals: list[RetrievalSignal] = []

    for rank, (strength, symbol) in enumerate(
        _dedupe_channel_results(channel), start=1
    ):
        signals.append(
            RetrievalSignal(
                kind=cast(
                    "Literal['exact_symbol', 'text_match', 'embedding_similarity', 'relation', 'proximity', 'repeated_evidence']",
                    _signal_kind_for_channel(channel_name),
                ),
                family=cast(
                    "Literal['lexical', 'semantic', 'task', 'graph', 'issue']",
                    _signal_family_for_channel(channel_name),
                ),
                target=symbol,
                producer_name=producer.producer_name,
                producer_version=producer.producer_version,
                capability_name=capability_name,
                capability_version=producer.capability_version,
                channel_name=channel_name,
                rank=rank,
                strength=strength,
            )
        )

    return signals


def _graph_channel_name_for_signal(signal: RetrievalSignal) -> ChannelName | None:
    """
    Map one graph producer signal onto a bounded ranking pseudo-channel.

    Parameters
    ----------
    signal : codira.query.signals.RetrievalSignal
        Graph-derived signal emitted by one enrichment producer.

    Returns
    -------
    codira.types.ChannelName | None
        Stable pseudo-channel name used during bounded graph ranking, or
        ``None`` when the signal should not influence retrieval-time ranking.
    """
    producer_to_channel: dict[str, ChannelName] = {
        "query-enrichment-call-graph": "call_graph",
        "query-enrichment-references": "references",
        "query-enrichment-include-graph": "include_graph",
    }
    return producer_to_channel.get(signal.producer_name)


def _strength_for_graph_signal(distance: int, support_count: int) -> float:
    """
    Compute a bounded retrieval strength for one graph-supported target.

    Parameters
    ----------
    distance : int
        Best graph distance observed for the target.
    support_count : int
        Number of raw graph relations supporting the same target.

    Returns
    -------
    float
        Deterministic bounded strength that rewards direct and repeated graph
        evidence without overwhelming stronger primary channels.
    """
    repeat_bonus = min(float(max(support_count - 1, 0)) * 0.1, 0.3)
    return (1.0 / float(max(distance, 1))) + repeat_bonus


def _bounded_graph_retrieval_signals(
    raw_graph_signals: list[RetrievalSignal],
) -> list[RetrievalSignal]:
    """
    Convert raw graph expansion evidence into bounded ranking signals.

    Parameters
    ----------
    raw_graph_signals : list[codira.query.signals.RetrievalSignal]
        Raw graph-derived signals collected around current top matches.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Deterministically ranked graph signals that can participate in the
        normal retrieval merge path.
    """
    grouped: dict[
        tuple[ChannelName, SymbolRow],
        tuple[RetrievalSignal, int, int],
    ] = {}

    for signal in sorted(raw_graph_signals, key=signal_sort_key):
        channel_name = _graph_channel_name_for_signal(signal)
        if channel_name is None:
            continue
        distance = signal.distance if signal.distance is not None else 1
        key = (channel_name, signal.target)
        if key not in grouped:
            grouped[key] = (signal, distance, 1)
            continue

        representative, best_distance, support_count = grouped[key]
        if distance < best_distance:
            representative = signal
            best_distance = distance
        grouped[key] = (representative, best_distance, support_count + 1)

    ranked_signals: list[RetrievalSignal] = []
    grouped_by_channel: dict[
        ChannelName,
        list[tuple[RetrievalSignal, int, int]],
    ] = {}
    for (channel_name, _target), value in grouped.items():
        grouped_by_channel.setdefault(channel_name, []).append(value)

    for channel_name, items in sorted(grouped_by_channel.items()):
        ranked_items = sorted(
            items,
            key=lambda item: (
                -_strength_for_graph_signal(item[1], item[2]),
                item[1],
                *_symbol_sort_key(item[0].target),
            ),
        )
        for rank, (signal, distance, support_count) in enumerate(
            ranked_items[:GRAPH_RETRIEVAL_LIMIT_PER_PRODUCER], start=1
        ):
            ranked_signals.append(
                replace(
                    signal,
                    channel_name=channel_name,
                    rank=rank,
                    strength=_strength_for_graph_signal(distance, support_count),
                    distance=distance,
                )
            )

    return sorted(ranked_signals, key=signal_sort_key)


def _collect_graph_retrieval_signals(
    request: GraphRetrievalRequest,
) -> list[RetrievalSignal]:
    """
    Collect bounded graph-derived retrieval signals around current top matches.

    Parameters
    ----------
    request : GraphRetrievalRequest
        Graph retrieval request carrying current matches and enabled graph
        expansion channels.

    Returns
    -------
    list[codira.query.signals.RetrievalSignal]
        Bounded graph-derived retrieval signals eligible for merged ranking.
    """
    raw_graph_signals: list[RetrievalSignal] = []
    expand_graph_related_symbols(
        GraphExpansionRequest(
            root=request.root,
            top_matches=request.top_matches,
            conn=request.conn,
            include_include_graph=request.include_include_graph,
            include_references=request.include_references,
            prefix=request.prefix,
            expanded=[],
            seen_symbols=set(request.top_matches),
            graph_signals=raw_graph_signals,
            classify_file_language=_classify_file_language,
            classify_file_role=_classify_file_role,
            include_target_module_name=_include_target_module_name,
            symbols_in_module=_symbols_in_module,
        )
    )
    return _bounded_graph_retrieval_signals(raw_graph_signals)


def _collect_retrieval_signals(
    bundles: list[ChannelBundle],
    *,
    producers: list[QueryProducerSpec],
) -> tuple[list[RetrievalSignal], SignalCollectionDiagnostics]:
    """
    Collect normalized retrieval signals through capability-aware producers.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Ranked channel bundles for the current query.
    producers : list[codira.query.producers.QueryProducerSpec]
        Query-layer retrieval producers synthesized for the same query.

    Returns
    -------
    tuple[list[codira.query.signals.RetrievalSignal], dict[str, object]]
        Deterministically ordered signals plus compact collection diagnostics.
    """
    bundles_by_channel = {channel_name: channel for channel_name, channel in bundles}
    signals: list[RetrievalSignal] = []
    used_producers: list[str] = []
    ignored_producers: list[str] = []

    for producer in producers:
        known_capabilities, _unknown_capabilities = (
            split_declared_retrieval_capabilities(producer.capabilities)
        )

        if producer.source_kind != "channel":
            ignored_producers.append(producer.producer_name)
            continue

        channel = bundles_by_channel.get(producer.source_name)
        if channel is None:
            ignored_producers.append(producer.producer_name)
            continue

        if not known_capabilities:
            ignored_producers.append(producer.producer_name)
            continue

        used_producers.append(producer.producer_name)
        signals.extend(_signals_from_channel_producer(producer, channel=channel))

    ordered_signals = sorted(signals, key=signal_sort_key)
    diagnostics = _signal_collection_diagnostics(
        ordered_signals,
        used_producers=used_producers,
        ignored_producers=ignored_producers,
    )
    return ordered_signals, diagnostics


def _signal_collection_diagnostics(
    signals: list[RetrievalSignal],
    *,
    used_producers: list[str],
    ignored_producers: list[str],
) -> SignalCollectionDiagnostics:
    """
    Summarize one normalized signal set for explain diagnostics.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals to summarize.
    used_producers : list[str]
        Producer identifiers that contributed at least one signal.
    ignored_producers : list[str]
        Producer identifiers that were available but did not contribute.

    Returns
    -------
    dict[str, object]
        Compact deterministic signal-collection diagnostics.
    """
    families: dict[str, int] = {}
    capabilities: dict[str, int] = {}

    for signal in signals:
        families[signal.family] = families.get(signal.family, 0) + 1
        capabilities[signal.capability_name] = (
            capabilities.get(signal.capability_name, 0) + 1
        )

    diagnostics: SignalCollectionDiagnostics = {
        "total_signals": len(signals),
        "families": dict(sorted(families.items())),
        "capabilities": dict(sorted(capabilities.items())),
        "used_producers": sorted(used_producers),
        "ignored_producers": sorted(ignored_producers),
    }
    return diagnostics


def _signal_preview(
    signals: list[RetrievalSignal],
    *,
    limit: int = 12,
) -> list[dict[str, object]]:
    """
    Build a compact explain preview for normalized retrieval signals.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals collected for the current query.
    limit : int, optional
        Maximum number of preview entries to emit.

    Returns
    -------
    list[dict[str, object]]
        Compact deterministic signal preview entries.
    """
    preview: list[dict[str, object]] = []

    for signal in sorted(signals, key=signal_sort_key)[:limit]:
        symbol_type, module_name, name, _file_path, lineno = signal.target
        entry: dict[str, object] = {
            "kind": signal.kind,
            "family": signal.family,
            "producer_name": signal.producer_name,
            "capability_name": signal.capability_name,
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "lineno": lineno,
        }
        if signal.channel_name is not None:
            entry["channel_name"] = signal.channel_name
        if signal.rank is not None:
            entry["rank"] = signal.rank
        if signal.strength is not None:
            entry["strength"] = round(signal.strength, 4)
        if signal.distance is not None:
            entry["distance"] = signal.distance
        if signal.source_symbol is not None:
            source_type, source_module, source_name, _source_file, source_lineno = (
                signal.source_symbol
            )
            entry["source"] = {
                "type": source_type,
                "module": source_module,
                "name": source_name,
                "lineno": source_lineno,
            }
        preview.append(entry)

    return preview


def _signal_summary_by_symbol(
    signals: list[RetrievalSignal],
    top_matches: list[SymbolRow],
) -> list[dict[str, object]]:
    """
    Summarize signal support for the current top matches.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Normalized signals collected for the current query.
    top_matches : list[codira.types.SymbolRow]
        Ranked top matches for the query.

    Returns
    -------
    list[dict[str, object]]
        Per-symbol signal summaries for explain output.
    """
    by_symbol: dict[SymbolRow, list[RetrievalSignal]] = {}
    for signal in signals:
        by_symbol.setdefault(signal.target, []).append(signal)

    entries: list[dict[str, object]] = []
    for symbol in top_matches:
        symbol_signals = sorted(by_symbol.get(symbol, []), key=signal_sort_key)
        if not symbol_signals:
            continue
        symbol_type, module_name, name, _file_path, lineno = symbol
        families: dict[str, int] = {}
        capabilities: dict[str, int] = {}
        producers: set[str] = set()

        for signal in symbol_signals:
            families[signal.family] = families.get(signal.family, 0) + 1
            capabilities[signal.capability_name] = (
                capabilities.get(signal.capability_name, 0) + 1
            )
            producers.add(signal.producer_name)

        entries.append(
            {
                "type": symbol_type,
                "module": module_name,
                "name": name,
                "lineno": lineno,
                "signal_count": len(symbol_signals),
                "families": dict(sorted(families.items())),
                "capabilities": dict(sorted(capabilities.items())),
                "producers": sorted(producers),
            }
        )

    return entries


def _get_channel_functions(
    plan: RetrievalPlan,
) -> list[
    tuple[
        ChannelName,
        Callable[
            [Path, str, sqlite3.Connection, QueryIntent, str | None],
            ChannelResults,
        ],
    ]
]:
    """
    Resolve enabled channel functions for a query intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan derived from query intent.

    Returns
    -------
    list[
        tuple[
            codira.types.ChannelName,
            collections.abc.Callable[
                [
                    pathlib.Path,
                    str,
                    sqlite3.Connection,
                    codira.query.classifier.QueryIntent,
                    str | None,
                ],
                codira.types.ChannelResults,
            ],
        ]
    ]
        Ordered channel names and their retrieval callables.
    """
    registry = _channel_registry()
    return [
        (name, registry[name].retrieve) for name in plan.channels if name in registry
    ]


def _retrieve_semantic_candidates(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    prefix: str | None,
) -> ChannelResults:
    """
    Deterministic semantic channel with independent candidate retrieval.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files. The current implementation
        does not need it directly.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification. The current implementation does not
        use it directly.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    codira.types.ChannelResults
        Ranked semantic candidates for the query.

    Notes
    -----
    The channel is deterministic and independent from the symbol channel. It
    scores token overlap against symbol names, module names, and optional
    docstring text when that auxiliary table exists.
    """

    del root

    tokens = [t.lower() for t in _tokenize(query) if len(t) >= 3]
    if not tokens:
        return []

    prefix_sql, prefix_params = prefix_clause(prefix, "f.path")
    rows = conn.execute(
        f"""
        SELECT s.type, s.module_name, s.name, f.path, s.lineno
        FROM symbol_index s
        JOIN files f
          ON s.file_id = f.id
        WHERE 1 = 1
        {prefix_sql}
        ORDER BY s.module_name, s.name, f.path, s.lineno
        LIMIT ?
        """,
        (*prefix_params, SEMANTIC_SCAN_LIMIT),
    ).fetchall()

    results: ChannelResults = []

    for row in rows:
        symbol = (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            int(row[4]),
        )

        symbol_type, module_name, name, _file_path, _lineno = symbol

        text_parts = [module_name.lower(), name.lower()]

        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT docstring FROM docstrings WHERE module=? AND name=?",
                (module_name, name),
            )
            doc_row = cursor.fetchone()
            if doc_row and doc_row[0]:
                text_parts.append(str(doc_row[0]).lower())
        except sqlite3.OperationalError:
            # docstrings table may not exist depending on index version
            pass

        semantic_score = 0.0

        for token in tokens:
            if token in name.lower():
                semantic_score += 3.0
            elif token in module_name.lower():
                semantic_score += 2.0
            elif any(token in part for part in text_parts):
                semantic_score += 1.0

        if semantic_score == 0.0:
            continue

        if symbol_type == "function":
            semantic_score += 0.5

        if name.startswith("_"):
            semantic_score -= 1.0

        if semantic_score >= SEMANTIC_WEIGHT:
            results.append((semantic_score, symbol))

    results.sort(key=_scored_symbol_sort_key)

    return results[:SEMANTIC_RESULT_LIMIT]


def _retrieve_embedding_candidates(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    intent: QueryIntent,
    prefix: str | None,
) -> ChannelResults:
    """
    Retrieve ranked candidates from the stored embedding channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification used to apply role-aware ranking bias.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.

    Returns
    -------
    codira.types.ChannelResults
        Ranked embedding-channel candidates for the query.
    """
    results = EMBEDDING_RETRIEVAL_PRODUCER.retrieve_candidates(
        EmbeddingRetrievalRequest(
            root=root,
            query=query,
            limit=EMBEDDING_RESULT_LIMIT,
            min_score=EMBEDDING_MIN_SCORE,
            prefix=prefix,
            conn=conn,
        )
    )
    sorted_results = list(results)
    sorted_results.sort(key=_scored_symbol_sort_key)
    return sorted_results


def _channel_registry() -> dict[ChannelName, QueryChannelSpec]:
    """
    Return query-channel specs keyed by channel name.

    Parameters
    ----------
    None

    Returns
    -------
    dict[codira.types.ChannelName, codira.query.producers.QueryChannelSpec]
        Mapping from channel names to retrieval functions and producer metadata.
    """
    return {
        "symbol": QueryChannelSpec(
            name="symbol",
            retrieve=_retrieve_symbol_candidates,
            producer=CHANNEL_PRODUCER_SPECS["symbol"],
        ),
        "embedding": QueryChannelSpec(
            name="embedding",
            retrieve=_retrieve_embedding_candidates,
            producer=CHANNEL_PRODUCER_SPECS["embedding"],
        ),
        "test": QueryChannelSpec(
            name="test",
            retrieve=_retrieve_test_candidates,
            producer=CHANNEL_PRODUCER_SPECS["test"],
        ),
        "script": QueryChannelSpec(
            name="script",
            retrieve=_retrieve_script_candidates,
            producer=CHANNEL_PRODUCER_SPECS["script"],
        ),
        "semantic": QueryChannelSpec(
            name="semantic",
            retrieve=_retrieve_semantic_candidates,
            producer=CHANNEL_PRODUCER_SPECS["semantic"],
        ),
    }


def _enabled_channels(plan: RetrievalPlan) -> set[ChannelName]:
    """
    Return the set of channels enabled for an intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan.

    Returns
    -------
    set[codira.types.ChannelName]
        Enabled retrieval channels.
    """
    return set(plan.channels)


def _channel_priority(plan: RetrievalPlan) -> dict[ChannelName, int]:
    """
    Return channel priority values for an intent.

    Parameters
    ----------
    plan : codira.query.classifier.RetrievalPlan
        Deterministic retrieval plan.

    Returns
    -------
    dict[codira.types.ChannelName, int]
        Lower values indicate higher routing priority.
    """
    return {channel: index for index, channel in enumerate(plan.channels)}


def _is_issue_query(query: str) -> bool:
    """
    Check whether a query targets documentation issues.

    Parameters
    ----------
    query : str
        User query string.

    Returns
    -------
    bool
        ``True`` when the query mentions issue-oriented documentation terms.
    """
    query_tokens = _tokenize(query)
    issue_tokens = {
        "doc",
        "docstring",
        "docs",
        "issue",
        "issues",
        "missing",
        "numpy",
        "section",
        "returns",
        "parameters",
    }
    return any(token in issue_tokens for token in query_tokens)


def _issue_driven_symbols(
    root: Path,
    query: str,
    conn: sqlite3.Connection,
    *,
    prefix: str | None = None,
) -> list[SymbolRow]:
    """
    Rank symbols that are implicated by matching docstring issues.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        User query string.
    conn : sqlite3.Connection
        Open database connection.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict issue ownership and symbol
        files.

    Returns
    -------
    list[codira.types.SymbolRow]
        Small set of issue-related symbols ordered by heuristic score.
    """
    issue_rows = docstring_issues(root, prefix=prefix, conn=conn)
    query_tokens = _tokenize(query)
    scored: dict[SymbolRow, int] = {}

    GENERIC_NAMES = {"main", "__init__", "run"}

    for issue in issue_rows:
        issue_type = issue[0]
        message = issue[1]
        message_lower = message.lower()

        if not any(token in message_lower for token in query_tokens):
            continue

        head = message.split(":", 1)[0]

        # Extract symbol name deterministically
        symbol_name: str | None = None

        if head.startswith("Function "):
            symbol_name = head[len("Function ") :]

        elif head.startswith("Module "):
            symbol_name = head[len("Module ") :].split(".")[-1]

        elif head.startswith("Method "):
            parts = head[len("Method ") :].split(".")
            if len(parts) == 2:
                symbol_name = parts[1]

        if not symbol_name:
            continue

        if symbol_name in GENERIC_NAMES:
            continue

        for symbol in find_symbol(root, symbol_name, prefix=prefix, conn=conn):
            module_name = symbol[1]

            # Reject obvious noise
            role = _classify_file_role(symbol[3], module_name)
            if role in {"test", "tooling"} or module_name.startswith("."):
                continue

            bonus = 3 if issue_type == "missing" else 1

            if symbol in scored:
                scored[symbol] += bonus
            else:
                scored[symbol] = bonus

    ranked = sorted(
        scored,
        key=lambda symbol: (
            -scored[symbol],
            symbol[3],
            symbol[4],
            symbol[2],
        ),
    )

    return ranked[:5]


def _collect_doc_issues_and_related(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    conn: sqlite3.Connection,
    *,
    prefix: str | None = None,
) -> tuple[list[tuple[str, str]], list[SymbolRow]]:
    """
    Collect related docstring issues and derive additional related symbols.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : sqlite3.Connection
        Open database connection.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict issue ownership and symbol
        files.

    Returns
    -------
    tuple[list[tuple[str, str]], list[codira.types.SymbolRow]]
        Related docstring issue rows and derived related symbols.
    """
    issue_rows = docstring_issues(root, prefix=prefix, conn=conn)

    issue_rows_filtered: list[tuple[str, str]] = []

    symbol_names = {name for _, _, name, _, _ in top_matches if name}

    for issue in issue_rows:
        issue_type = issue[0]
        message = issue[1]
        if not any(name in message for name in symbol_names):
            continue

        # --- FILTER NOISE: skip tests and scripts ---
        if "tests." in message or "scripts." in message:
            continue

        issue_rows_filtered.append((issue_type, message))

    doc_issues: list[tuple[str, str]] = issue_rows_filtered[:20]

    related_symbols: list[SymbolRow] = []

    for _, message in doc_issues:
        parts = message.split(":")[0].split()
        if len(parts) >= 2:
            symbol_name = parts[-1]
            related_symbols.extend(
                find_symbol(root, symbol_name, prefix=prefix, conn=conn)
            )

    return doc_issues, related_symbols


def _is_test_file(path: str) -> bool:
    """
    Check whether a path looks like a test file.

    Parameters
    ----------
    path : str
        File path to classify.

    Returns
    -------
    bool
        ``True`` when the path looks like a pytest-style test module.
    """
    return _classify_file_role(path, "") == "test"


def _dedupe_and_cap_references(
    refs: list[ReferenceRow],
    *,
    max_per_file: int = 3,
    min_line_gap: int = 5,
) -> list[ReferenceRow]:
    """
    Dedupe reference hits and cap density per file.

    Parameters
    ----------
    refs : list[codira.types.ReferenceRow]
        Raw reference hits to reduce.
    max_per_file : int, optional
        Maximum number of references retained per file.
    min_line_gap : int, optional
        Minimum spacing between retained references in the same file.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Reduced reference hits ordered by file and line number.
    """
    # group by file
    by_file: dict[str, list[int]] = {}

    for file_path, lineno in refs:
        by_file.setdefault(file_path, []).append(lineno)

    result: list[ReferenceRow] = []

    for file_path in sorted(by_file):
        lines = sorted(by_file[file_path])

        kept: list[int] = []
        last_kept: int | None = None

        for ln in lines:
            if last_kept is None or abs(ln - last_kept) >= min_line_gap:
                kept.append(ln)
                last_kept = ln

            if len(kept) >= max_per_file:
                break

        for ln in kept:
            result.append((file_path, ln))

    return result


def _expand_include_graph_neighbors(
    root: Path,
    symbol: SymbolRow,
    conn: sqlite3.Connection,
    *,
    prefix: str | None,
    graph_signals: list[RetrievalSignal] | None = None,
) -> tuple[list[SymbolRow], list[dict[str, object]]]:
    """
    Expand one symbol through direct local C include relationships.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    symbol : codira.types.SymbolRow
        Seed symbol whose owning module should be expanded.
    conn : sqlite3.Connection
        Open database connection reused for exact graph lookups.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized include-proximity
        evidence when supplied.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], list[dict[str, object]]]
        Related symbols discovered through direct include edges plus
        deterministic include-expansion diagnostics.
    """
    module_name = symbol[1]
    file_language = _classify_file_language(symbol[3])
    if file_language != "c":
        return [], []

    related: list[SymbolRow] = []
    seen: set[tuple[str, str]] = set()
    diagnostics: list[dict[str, object]] = []

    def _append_symbols(
        target_module: str,
        *,
        via_module: str,
        target_name: str,
        kind: str,
        direction: str,
    ) -> None:
        for candidate in _symbols_in_module(root, target_module, prefix=prefix):
            key = (candidate[1], candidate[2])
            if key in seen:
                continue
            seen.add(key)
            related.append(candidate)
            diagnostics.append(
                {
                    "seed_module": module_name,
                    "via_module": via_module,
                    "target_name": target_name,
                    "kind": kind,
                    "direction": direction,
                    "expanded_module": candidate[1],
                    "expanded_name": candidate[2],
                }
            )
            if graph_signals is not None:
                graph_signals.append(
                    INCLUDE_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                        kind="proximity",
                        target=candidate,
                        source_symbol=symbol,
                        distance=1,
                    )
                )

    pending_modules: list[str] = [module_name]
    visited_modules: set[str] = set()

    while pending_modules:
        current_module = pending_modules.pop(0)
        if current_module in visited_modules:
            continue
        visited_modules.add(current_module)

        outgoing_edges: list[IncludeEdgeRow] = find_include_edges(
            EdgeQueryRequest(
                root=root,
                name=current_module,
                prefix=prefix,
                conn=conn,
            )
        )
        for _owner_module, target_name, kind, _lineno in outgoing_edges:
            target_module = _include_target_module_name(target_name, kind)
            if target_module is None:
                continue
            _append_symbols(
                target_module,
                via_module=current_module,
                target_name=target_name,
                kind=kind,
                direction="outgoing",
            )
            if target_module not in visited_modules:
                pending_modules.append(target_module)

    current_module_path = Path(*module_name.split("."))
    current_target_name = f"{current_module_path.name}.h"
    if len(current_module_path.parts) > 1:
        current_target_name = str(
            Path(*current_module_path.parts[:-1]) / current_target_name
        )

    incoming_edges: list[IncludeEdgeRow] = find_include_edges(
        EdgeQueryRequest(
            root=root,
            name=current_target_name,
            incoming=True,
            prefix=prefix,
            conn=conn,
        )
    )
    for owner_module, _target_name, _kind, _lineno in incoming_edges:
        _append_symbols(
            owner_module,
            via_module=owner_module,
            target_name=current_target_name,
            kind="include_local",
            direction="incoming",
        )

    return related, diagnostics


def _add_related_symbol(
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
    symbol: SymbolRow,
) -> None:
    """
    Add one related symbol when it survives expansion filters.

    Parameters
    ----------
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.
    symbol : codira.types.SymbolRow
        Candidate related symbol discovered during expansion.

    Returns
    -------
    None
        The symbol is appended in place when it passes all filters.
    """
    symbol_type, module_name, name, _file_path, _lineno = symbol
    if symbol in seen_symbols:
        return
    if name.startswith("_"):
        return
    role = _classify_file_role(symbol[3], module_name)
    if symbol_type == "module" and role in {"test", "tooling"}:
        return
    if role in {"test", "tooling"}:
        return
    seen_symbols.add(symbol)
    expanded.append(symbol)


def _expand_graph_related_symbols(
    root: Path,
    top_matches: list[SymbolRow],
    conn: sqlite3.Connection,
    *,
    include_include_graph: bool,
    include_references: bool,
    prefix: str | None,
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
    graph_signals: list[RetrievalSignal] | None = None,
) -> list[dict[str, object]]:
    """
    Expand top matches through include, call, and callable-reference graphs.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : sqlite3.Connection
        Open database connection reused for exact graph lookups.
    include_include_graph : bool
        Whether include-graph expansion is enabled.
    include_references : bool
        Whether callable-reference expansion is enabled.
    prefix : str | None
        Absolute normalized prefix used to restrict owner files and symbols.
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized graph evidence when
        supplied.

    Returns
    -------
    list[dict[str, object]]
        Deterministic include-graph diagnostics collected during expansion.
    """
    return expand_graph_related_symbols(
        GraphExpansionRequest(
            root=root,
            top_matches=top_matches,
            conn=conn,
            include_include_graph=include_include_graph,
            include_references=include_references,
            prefix=prefix,
            expanded=expanded,
            seen_symbols=seen_symbols,
            graph_signals=graph_signals,
            classify_file_language=_classify_file_language,
            classify_file_role=_classify_file_role,
            include_target_module_name=_include_target_module_name,
            symbols_in_module=lambda module_root, module_name: _symbols_in_module(
                module_root,
                module_name,
                prefix=prefix,
            ),
        )
    )


def _expand_module_related_symbols(
    root: Path,
    top_matches: list[SymbolRow],
    *,
    prefix: str | None,
    expanded: list[SymbolRow],
    seen_symbols: set[SymbolRow],
) -> None:
    """
    Expand top matches to other public symbols in the same modules.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for exact module lookups.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    prefix : str | None
        Absolute normalized prefix used to restrict module symbols.
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.
    seen_symbols : set[codira.types.SymbolRow]
        Symbols already admitted to the expanded result set.

    Returns
    -------
    None
        Related module-local symbols are appended in place.
    """
    seen_modules: set[str] = set()

    for _, module_name, _, _, _ in top_matches:
        if module_name in seen_modules:
            continue
        seen_modules.add(module_name)
        for symbol in _symbols_in_module(root, module_name, prefix=prefix):
            if symbol[2].startswith("_"):
                continue
            _add_related_symbol(expanded, seen_symbols, symbol)


def _finalize_expanded_symbols(expanded: list[SymbolRow]) -> list[SymbolRow]:
    """
    Dedupe expanded symbols by module and name and cap the final result.

    Parameters
    ----------
    expanded : list[codira.types.SymbolRow]
        Pending expanded symbols collected for the query.

    Returns
    -------
    list[codira.types.SymbolRow]
        Deduplicated and capped expanded symbols.
    """
    seen_keys: set[tuple[str, str]] = set()
    deduped: list[SymbolRow] = []

    for symbol_type, module_name, name, file_path, lineno in expanded:
        key = (module_name, name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append((symbol_type, module_name, name, file_path, lineno))

    return deduped[:20]


def _collect_reference_rows(
    root: Path,
    top_matches: list[SymbolRow],
    *,
    include_references: bool,
    prefix: str | None,
) -> list[ReferenceRow]:
    """
    Collect cross-module reference rows for the primary top matches.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for project-file scans.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    include_references : bool
        Whether reference collection is enabled.
    prefix : str | None
        Absolute normalized prefix used to restrict scanned files.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Deduplicated and capped reference rows in deterministic order.
    """
    if not include_references:
        return []

    symbol_names = {name for _, _, name, _, _ in top_matches if name}
    project_files = [
        path
        for path in iter_project_files(
            root,
            analyzers=active_language_analyzers(),
        )
        if path_has_prefix(path, prefix)
    ]
    top_files = {file_path for _, _, _, file_path, _ in top_matches}
    file_cache: dict[Path, list[str]] = {}
    test_refs: list[ReferenceRow] = []
    other_refs: list[ReferenceRow] = []

    for name in symbol_names:
        for file_path, lineno in _find_references(
            root,
            name,
            project_files,
            file_cache=file_cache,
        ):
            if file_path in top_files:
                continue
            ref = (file_path, lineno)
            if _is_test_file(file_path):
                test_refs.append(ref)
            else:
                other_refs.append(ref)

    unique_refs: list[ReferenceRow] = []
    seen_refs: set[ReferenceRow] = set()
    for ref in test_refs + other_refs:
        if ref in seen_refs:
            continue
        seen_refs.add(ref)
        unique_refs.append(ref)

    return _dedupe_and_cap_references(unique_refs)[:20]


def _expand_and_collect_references(
    root: Path,
    top_matches: list[SymbolRow],
    conn: sqlite3.Connection,
    *,
    include_include_graph: bool,
    include_references: bool,
    prefix: str | None = None,
    graph_signals: list[RetrievalSignal] | None = None,
) -> tuple[list[SymbolRow], list[ReferenceRow], ExpansionDiagnostics]:
    """
    Perform module expansion and collect cross-module references.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used for file discovery and path normalization.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols for the query.
    conn : sqlite3.Connection
        Open database connection reused for graph lookups and symbol
        expansion.
    include_include_graph : bool
        Whether include-graph expansion is enabled by the retrieval plan.
    include_references : bool
        Whether cross-module reference collection is enabled by the retrieval
        plan.
    prefix : str | None, optional
        Absolute normalized prefix used to restrict owner files, expanded
        symbols, and scanned references.
    graph_signals : list[codira.query.signals.RetrievalSignal] | None, optional
        Mutable signal buffer that receives normalized graph evidence when
        supplied.

    Returns
    -------
    tuple[
        list[codira.types.SymbolRow],
        list[codira.types.ReferenceRow],
        codira.query.context.ExpansionDiagnostics,
    ]
        Expanded related symbols, cross-module reference locations, and
        deterministic expansion diagnostics.

    Notes
    -----
    Expansion excludes private helpers and removes test or script modules to
    keep the final context focused on reusable project code. It also uses
    stored call edges and callable references to pull in cross-module related
    symbols around the primary matches.
    """
    expanded: list[SymbolRow] = []
    seen_symbols: set[SymbolRow] = set(top_matches)
    include_expansion = _expand_graph_related_symbols(
        root,
        top_matches,
        conn,
        include_include_graph=include_include_graph,
        include_references=include_references,
        prefix=prefix,
        expanded=expanded,
        seen_symbols=seen_symbols,
        graph_signals=graph_signals,
    )
    _expand_module_related_symbols(
        root,
        top_matches,
        prefix=prefix,
        expanded=expanded,
        seen_symbols=seen_symbols,
    )
    expanded = _finalize_expanded_symbols(expanded)
    unique_refs = _collect_reference_rows(
        root,
        top_matches,
        include_references=include_references,
        prefix=prefix,
    )
    diagnostics: ExpansionDiagnostics = {"include_graph": include_expansion}
    return expanded, unique_refs, diagnostics


def _prompt_symbol_line(root: Path, symbol: SymbolRow) -> str:
    """
    Render a one-line symbol entry for agent prompts.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    symbol : codira.types.SymbolRow
        Symbol row to render.

    Returns
    -------
    str
        Prompt-friendly single-line symbol description.
    """
    symbol_type, module_name, name, file_path, lineno = symbol

    try:
        rel_path = str(Path(file_path).relative_to(root))
    except ValueError:
        rel_path = str(file_path)

    if symbol_type == "module":
        return f"- {symbol_type} {module_name} ({rel_path}:{lineno})"

    return f"- {symbol_type} {module_name}.{name} ({rel_path}:{lineno})"


def _render_agent_prompt(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
) -> str:
    """
    Render the agent prompt variant of the query context.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked matches.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for the selected symbols.

    Returns
    -------
    str
        Prompt-formatted query context.
    """
    return build_prompt(
        PromptBuildRequest(
            root=root,
            query=query,
            top_matches=top_matches,
            doc_issues=doc_issues,
            expanded=expanded,
            unique_refs=unique_refs,
            prompt_symbol_line=_prompt_symbol_line,
            format_enriched_symbol=_format_enriched_symbol,
        )
    )


def _approx_token_count(lines: list[str]) -> int:
    """
    Approximate token count using whitespace splitting.

    Parameters
    ----------
    lines : list[str]
        Lines whose token count should be estimated.

    Returns
    -------
    int
        Approximate token count.
    """
    return sum(len(line.split()) for line in lines)


def _render_context_json(
    root: Path,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
    *,
    confidence_map: dict[SymbolRow, float] | None = None,
    explain: bool = False,
    intent: QueryIntent | None = None,
    plan: RetrievalPlan | None = None,
    enabled_channels: set[ChannelName] | None = None,
    channel_priority: dict[ChannelName, int] | None = None,
    ordered_channels: list[ChannelName] | None = None,
    producers: list[ProducerDiagnosticsEntry] | None = None,
    signal_collection: SignalCollectionDiagnostics | None = None,
    signal_preview: list[dict[str, object]] | None = None,
    signal_merge: list[dict[str, object]] | None = None,
    bundles: list[ChannelBundle] | None = None,
    provenance: MergeDiagnostics | None = None,
    diversity: DiversityDiagnostics | None = None,
    expansion: ExpansionDiagnostics | None = None,
) -> str:
    """
    Render context output as structured JSON.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to format file paths.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.
    confidence_map : dict[codira.types.SymbolRow, float] | None, optional
        Confidence values keyed by symbol.
    explain : bool, optional
        Whether explain metadata should be included.
    intent : codira.query.classifier.QueryIntent | None, optional
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None, optional
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None, optional
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None, optional
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None, optional
        Ordered channel names.
    producers : list[dict[str, object]] | None, optional
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : dict[str, object] | None, optional
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None, optional
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None, optional
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None, optional
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None, optional
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None, optional
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None, optional
        Expansion diagnostics for graph-derived module expansion.

    Returns
    -------
    str
        JSON-encoded context payload.
    """
    status = "ok" if top_matches else "no_matches"
    _context_blocks: list[list[str]] = []
    _current_tokens = 0

    for s in top_matches[:ENRICHED_CONTEXT_LIMIT]:
        block = _format_enriched_symbol(root, s, {})
        block_tokens = _approx_token_count(block)

        if _current_tokens + block_tokens > MAX_TOKENS:
            break

        _context_blocks.append(block)
        _current_tokens += block_tokens

    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "top_matches": [
            {
                "type": t,
                "module": m,
                "name": n,
                "file": f,
                "lineno": lin,
                "confidence": (
                    confidence_map.get((t, m, n, f, lin), 1.0)
                    if confidence_map
                    else 1.0
                ),
            }
            for t, m, n, f, lin in top_matches
        ],
        "doc_issues": [{"type": t, "message": m} for t, m in doc_issues],
        "context": _context_blocks,
        "module_expansion": [
            {
                "type": t,
                "module": m,
                "name": n,
                "file": f,
                "lineno": lin,
            }
            for t, m, n, f, lin in expanded
        ],
        "references": [{"file": f, "lineno": lin} for f, lin in unique_refs],
    }

    if explain:
        embedding_backend = get_embedding_backend()
        explain_block: dict[str, object] = {}

        explain_block["environment"] = {
            "codira_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "embedding_backend": {
                "name": embedding_backend.name,
                "version": embedding_backend.version,
                "dim": embedding_backend.dim,
            },
        }

        if intent:
            explain_block["intent"] = {
                "is_identifier_query": intent.is_identifier_query,
                "is_test_related": intent.is_test_related,
                "is_script_related": intent.is_script_related,
                "is_multi_term": intent.is_multi_term,
                "primary_intent": intent.primary_intent,
                "raw": intent.raw,
            }

        if plan is not None:
            explain_block["planner"] = {
                "primary_intent": plan.primary_intent,
                "channels": list(plan.channels),
                "include_doc_issues": plan.include_doc_issues,
                "include_include_graph": plan.include_include_graph,
                "include_references": plan.include_references,
            }

        if enabled_channels is not None:
            explain_block["enabled_channels"] = sorted(enabled_channels)

        if channel_priority is not None:
            explain_block["channel_priority"] = channel_priority

        if ordered_channels is not None:
            explain_block["ordered_channels"] = ordered_channels

        if producers is not None:
            explain_block["retrieval_producers"] = producers

        if signal_collection is not None:
            explain_block["signal_collection"] = signal_collection

        if signal_preview is not None:
            explain_block["signals"] = signal_preview

        if signal_merge is not None:
            explain_block["signal_merge"] = signal_merge

        if bundles is not None:
            channel_results: dict[str, list[dict[str, object]]] = {}

            for channel_name, channel in bundles:
                entries: list[dict[str, object]] = []

                for score, symbol in channel[:5]:
                    symbol_type, module_name, name, _, lineno = symbol

                    entries.append(
                        {
                            "type": symbol_type,
                            "module": module_name,
                            "name": name,
                            "lineno": lineno,
                            "score": round(score, 2),
                        }
                    )

                channel_results[channel_name] = entries

            explain_block["channel_results"] = channel_results

        if provenance is not None:
            merge_entries: list[dict[str, object]] = []

            for symbol in top_matches:
                merge_details = provenance.get(symbol)
                if not merge_details:
                    continue

                symbol_type, module_name, name, _, lineno = symbol
                role = _classify_file_role(symbol[3], module_name)
                role_bias = _file_role_bias(role, intent)
                merge_channels = cast("dict[str, float]", merge_details["channels"])
                merge_families = cast("dict[str, float]", merge_details["families"])
                merge_rrf_score = cast("float", merge_details["rrf_score"])
                merge_evidence_bonus = cast("float", merge_details["evidence_bonus"])
                merge_role_bonus = cast("float", merge_details["role_bonus"])
                merge_score = cast("float", merge_details["merge_score"])
                merge_winner = cast("str", merge_details["winner"])

                merge_entries.append(
                    {
                        "type": symbol_type,
                        "module": module_name,
                        "name": name,
                        "lineno": lineno,
                        "channels": merge_channels,
                        "families": merge_families,
                        "rrf_score": round(merge_rrf_score, 4),
                        "evidence_bonus": round(merge_evidence_bonus, 4),
                        "role_bonus": round(merge_role_bonus, 4),
                        "merge_score": round(merge_score, 4),
                        "winner": merge_winner,
                        "role": role,
                        "role_bias": role_bias,
                    }
                )

            explain_block["merge"] = merge_entries

        if diversity is not None:
            explain_block["diversity"] = diversity

        if expansion is not None:
            explain_block["expansion"] = expansion

        result["explain"] = explain_block

    return json.dumps(result, indent=2)


def _render_context_prompt(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
) -> str:
    """
    Render context output in prompt form.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.

    Returns
    -------
    str
        Prompt-formatted query context.
    """
    return _render_agent_prompt(
        root,
        query,
        top_matches,
        doc_issues,
        expanded,
        unique_refs,
    )


def _render_context(
    root: Path,
    query: str,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
    *,
    confidence_map: dict[SymbolRow, float] | None = None,
    as_json: bool = False,
    as_prompt: bool = False,
    explain: bool = False,
    intent: QueryIntent | None = None,
    plan: RetrievalPlan | None = None,
    enabled_channels: set[ChannelName] | None = None,
    channel_priority: dict[ChannelName, int] | None = None,
    ordered_channels: list[ChannelName] | None = None,
    producers: list[ProducerDiagnosticsEntry] | None = None,
    signal_collection: SignalCollectionDiagnostics | None = None,
    signal_preview: list[dict[str, object]] | None = None,
    signal_merge: list[dict[str, object]] | None = None,
    bundles: list[ChannelBundle] | None = None,
    provenance: MergeDiagnostics | None = None,
    diversity: DiversityDiagnostics | None = None,
    expansion: ExpansionDiagnostics | None = None,
) -> str:
    """
    Render final structured context output.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    query : str
        Original user query.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.
    confidence_map : dict[codira.types.SymbolRow, float] | None, optional
        Confidence values keyed by symbol.
    as_json : bool, optional
        Whether to render JSON output.
    as_prompt : bool, optional
        Whether to render prompt output.
    explain : bool, optional
        Whether to include explain metadata.
    intent : codira.query.classifier.QueryIntent | None, optional
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None, optional
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None, optional
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None, optional
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None, optional
        Ordered channel names.
    producers : list[dict[str, object]] | None, optional
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : dict[str, object] | None, optional
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None, optional
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None, optional
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None, optional
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None, optional
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None, optional
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None, optional
        Expansion diagnostics for graph-derived module expansion.

    Returns
    -------
    str
        Rendered context in plain-text, JSON, or prompt form.
    """
    if as_json:
        return _render_context_json(
            root,
            top_matches,
            doc_issues,
            expanded,
            unique_refs,
            confidence_map=confidence_map,
            explain=explain,
            intent=intent,
            plan=plan,
            enabled_channels=enabled_channels,
            channel_priority=channel_priority,
            ordered_channels=ordered_channels,
            producers=producers,
            signal_collection=signal_collection,
            signal_preview=signal_preview,
            signal_merge=signal_merge,
            bundles=bundles,
            provenance=provenance,
            diversity=diversity,
            expansion=expansion,
        )

    if as_prompt:
        return _render_context_prompt(
            root,
            query,
            top_matches,
            doc_issues,
            expanded,
            unique_refs,
        )

    lines: list[str] = []

    if explain:
        _append_explain_sections(
            lines,
            explain=explain,
            intent=intent,
            plan=plan,
            enabled_channels=enabled_channels,
            channel_priority=channel_priority,
            ordered_channels=ordered_channels,
            producers=producers,
            signal_collection=signal_collection,
            signal_preview=signal_preview,
            signal_merge=signal_merge,
            bundles=bundles,
            provenance=provenance,
            diversity=diversity,
            expansion=expansion,
            top_matches=top_matches,
        )

    _append_main_context_sections(
        lines,
        root,
        top_matches,
        doc_issues,
        expanded,
        unique_refs,
    )

    return "\n".join(lines)


def _append_explain_sections(
    lines: list[str],
    *,
    explain: bool,
    intent: QueryIntent | None,
    plan: RetrievalPlan | None,
    enabled_channels: set[ChannelName] | None,
    channel_priority: dict[ChannelName, int] | None,
    ordered_channels: list[ChannelName] | None,
    producers: list[ProducerDiagnosticsEntry] | None,
    signal_collection: SignalCollectionDiagnostics | None,
    signal_preview: list[dict[str, object]] | None,
    signal_merge: list[dict[str, object]] | None,
    bundles: list[ChannelBundle] | None,
    provenance: MergeDiagnostics | None,
    diversity: DiversityDiagnostics | None,
    expansion: ExpansionDiagnostics | None,
    top_matches: list[SymbolRow],
) -> None:
    """
    Append explain-mode sections to the plain-text output buffer.

    Parameters
    ----------
    lines : list[str]
        Mutable output buffer.
    explain : bool
        Whether explain sections should be rendered.
    intent : codira.query.classifier.QueryIntent | None
        Structured query classification.
    plan : codira.query.classifier.RetrievalPlan | None
        Deterministic retrieval plan derived from query intent.
    enabled_channels : set[codira.types.ChannelName] | None
        Channels enabled for the query.
    channel_priority : dict[codira.types.ChannelName, int] | None
        Channel priority mapping.
    ordered_channels : list[codira.types.ChannelName] | None
        Ordered channel names.
    producers : list[dict[str, object]] | None
        Retrieval-producer diagnostics synthesized from query producer specs.
    signal_collection : dict[str, object] | None
        Compact diagnostics describing capability-gated signal collection.
    signal_preview : list[dict[str, object]] | None
        Compact preview of normalized retrieval signals.
    signal_merge : list[dict[str, object]] | None
        Per-top-match signal attribution summaries.
    bundles : list[codira.types.ChannelBundle] | None
        Raw channel results.
    provenance : codira.query.context.MergeDiagnostics | None
        Merge diagnostics for ranked symbols.
    diversity : codira.query.context.DiversityDiagnostics | None
        Diversity-selection diagnostics for merged symbols.
    expansion : codira.query.context.ExpansionDiagnostics | None
        Expansion diagnostics for graph-derived module expansion.
    top_matches : list[codira.types.SymbolRow]
        Primary merged symbols to explain.

    Returns
    -------
    None
        The explain sections are appended to ``lines`` in place.

    Notes
    -----
    Rendering is gated by ``explain``. When explain mode is disabled, the
    function leaves ``lines`` unchanged.
    """
    if explain:
        lines.append("=== EXPLAIN: ENVIRONMENT ===")
        embedding_backend = get_embedding_backend()
        lines.append(f"codira_version: {__version__}")
        lines.append(f"schema_version: {SCHEMA_VERSION}")
        lines.append(
            "embedding_backend: "
            f"{embedding_backend.name}"
            f" version={embedding_backend.version}"
            f" dim={embedding_backend.dim}"
        )
        lines.append("")
        lines.append("=== EXPLAIN: QUERY INTENT ===")
        if intent:
            lines.append(f"is_identifier_query: {intent.is_identifier_query}")
            lines.append(f"is_test_related: {intent.is_test_related}")
            lines.append(f"is_script_related: {intent.is_script_related}")
            lines.append(f"is_multi_term: {intent.is_multi_term}")
            lines.append(f"primary_intent: {intent.primary_intent}")
            lines.append(f"raw: {intent.raw}")

        lines.append("\n=== EXPLAIN: CHANNEL ROUTING ===")
        if plan is not None:
            lines.append(f"planner.primary_intent: {plan.primary_intent}")
            lines.append(f"planner.channels: {list(plan.channels)}")
            lines.append(f"planner.include_doc_issues: {plan.include_doc_issues}")
            lines.append(f"planner.include_include_graph: {plan.include_include_graph}")
            lines.append(f"planner.include_references: {plan.include_references}")
        if enabled_channels is not None:
            lines.append(f"enabled_channels: {sorted(enabled_channels)}")
        if channel_priority is not None:
            lines.append(f"channel_priority: {channel_priority}")
        if ordered_channels is not None:
            lines.append(f"ordered_channels: {ordered_channels}")
        if producers is not None:
            lines.append("retrieval_producers:")
            for producer in producers:
                lines.append(
                    "  "
                    f"{producer['producer_name']}"
                    f" v{producer['producer_version']}"
                    f" capability_version={producer['capability_version']}"
                    f" source={producer['source_kind']}:{producer['source_name']}"
                )
                lines.append(f"    known_capabilities={producer['known_capabilities']}")
                lines.append(
                    f"    unknown_capabilities={producer['unknown_capabilities']}"
                )
        if signal_collection is not None:
            lines.append(
                f"signal_collection: total_signals={signal_collection['total_signals']}"
            )
            lines.append(f"  families={signal_collection['families']}")
            lines.append(f"  capabilities={signal_collection['capabilities']}")
            lines.append(f"  used_producers={signal_collection['used_producers']}")
            lines.append(
                f"  ignored_producers={signal_collection['ignored_producers']}"
            )

        lines.append("")

    if explain and signal_preview is not None:
        lines.append("=== EXPLAIN: SIGNALS ===")
        for entry in signal_preview:
            label = (
                f"{entry['kind']} {entry['module']}.{entry['name']}:{entry['lineno']}"
            )
            lines.append(
                "  "
                f"{label} family={entry['family']}"
                f" producer={entry['producer_name']}"
                f" capability={entry['capability_name']}"
            )
            if "channel_name" in entry:
                lines.append(
                    "    "
                    f"channel={entry['channel_name']}"
                    f" rank={entry.get('rank')}"
                    f" strength={entry.get('strength')}"
                )
            if "distance" in entry:
                lines.append(f"    distance={entry['distance']}")
            if "source" in entry:
                source = cast("dict[str, object]", entry["source"])
                lines.append(
                    f"    source={source['module']}.{source['name']}:{source['lineno']}"
                )

        lines.append("")

    if explain and bundles is not None:
        lines.append("=== EXPLAIN: CHANNEL RESULTS ===")

        for channel_name, channel in sorted(bundles, key=lambda item: item[0]):
            lines.append(f"{channel_name}:")

            if not channel:
                lines.append("  (no results)")
                continue

            for score, symbol in channel[:5]:
                symbol_type, module_name, name, _, lineno = symbol

                if symbol_type == "module":
                    label = f"{module_name}:{lineno}"
                else:
                    label = f"{module_name}.{name}:{lineno}"

                lines.append(f"  {score:.2f} -> {label}")

        lines.append("")

    if explain and signal_merge is not None:
        lines.append("=== EXPLAIN: SIGNAL MERGE ===")
        for entry in signal_merge:
            lines.append(
                "  "
                f"{entry['module']}.{entry['name']}:{entry['lineno']}"
                f" signal_count={entry['signal_count']}"
            )
            lines.append(f"    families={entry['families']}")
            lines.append(f"    capabilities={entry['capabilities']}")
            lines.append(f"    producers={entry['producers']}")

        lines.append("")

    if explain and provenance is not None:
        lines.append("=== EXPLAIN: MERGE ===")

        for symbol in top_matches:
            symbol_type, module_name, name, _, lineno = symbol

            if symbol_type == "module":
                label = f"{module_name}:{lineno}"
            else:
                label = f"{module_name}.{name}:{lineno}"

            merge_details = provenance.get(symbol)

            if not merge_details:
                continue

            lines.append(label)
            role = _classify_file_role(symbol[3], module_name)
            role_bias = _file_role_bias(role, intent)
            merge_rrf_score = cast("float", merge_details["rrf_score"])
            merge_evidence_bonus = cast("float", merge_details["evidence_bonus"])
            merge_role_bonus = cast("float", merge_details["role_bonus"])
            merge_score = cast("float", merge_details["merge_score"])
            lines.append(
                "  "
                f"winner={cast('str', merge_details['winner'])} "
                f"rrf_score={merge_rrf_score:.4f} "
                f"evidence_bonus={merge_evidence_bonus:.4f} "
                f"role_bonus={merge_role_bonus:.4f} "
                f"merge_score={merge_score:.4f}"
            )
            lines.append(f"  role={role} role_bias={role_bias}")

            family_scores = cast("dict[str, float]", merge_details["families"])
            for family_name, score in family_scores.items():
                lines.append(f"  family.{family_name}: {score:.2f}")

            channel_scores = cast("dict[str, float]", merge_details["channels"])
            for channel_name, score in channel_scores.items():
                lines.append(f"  channel.{channel_name}: {score:.2f}")

        lines.append("")

    if explain and diversity is not None:
        lines.append("=== EXPLAIN: DIVERSITY ===")
        lines.append(f"max_per_file: {MERGE_MAX_PER_FILE}")
        lines.append(f"role_caps: {MERGE_ROLE_CAPS}")
        lines.append(f"language_caps: {MERGE_LANGUAGE_CAPS}")

        selected_entries = diversity.get("selected")
        if isinstance(selected_entries, list) and selected_entries:
            lines.append("selected:")
            for entry in selected_entries[: len(top_matches)]:
                if not isinstance(entry, dict):
                    continue
                label = (
                    f"{entry.get('module')}.{entry.get('name')}:{entry.get('lineno')}"
                )
                lines.append(
                    "  "
                    f"{label} role={entry.get('role')} "
                    f"language={entry.get('language')} "
                    f"stage={entry.get('selection_stage')}"
                )

        deferred_entries = diversity.get("deferred")
        if isinstance(deferred_entries, list) and deferred_entries:
            lines.append("deferred:")
            for entry in deferred_entries[:5]:
                if not isinstance(entry, dict):
                    continue
                label = (
                    f"{entry.get('module')}.{entry.get('name')}:{entry.get('lineno')}"
                )
                lines.append(
                    "  "
                    f"{label} role={entry.get('role')} "
                    f"language={entry.get('language')} "
                    f"reason={entry.get('reason')}"
                )

        lines.append("")

    if explain and expansion is not None:
        include_entries = expansion.get("include_graph")
        if isinstance(include_entries, list) and include_entries:
            lines.append("=== EXPLAIN: EXPANSION ===")
            lines.append("include_graph:")
            for entry in include_entries[:10]:
                if not isinstance(entry, dict):
                    continue
                lines.append(
                    "  "
                    f"seed={entry.get('seed_module')} "
                    f"via={entry.get('via_module')} "
                    f"target={entry.get('target_name')} "
                    f"direction={entry.get('direction')} "
                    f"expanded={entry.get('expanded_module')}.{entry.get('expanded_name')}"
                )
            lines.append("")


def _append_main_context_sections(
    lines: list[str],
    root: Path,
    top_matches: list[SymbolRow],
    doc_issues: list[tuple[str, str]],
    expanded: list[SymbolRow],
    unique_refs: list[ReferenceRow],
) -> None:
    """
    Append the main plain-text context sections to the output buffer.

    Parameters
    ----------
    lines : list[str]
        Mutable output buffer.
    root : pathlib.Path
        Repository root used to relativize paths.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    doc_issues : list[tuple[str, str]]
        Related docstring issues.
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.
    unique_refs : list[codira.types.ReferenceRow]
        Cross-reference locations for selected symbols.

    Returns
    -------
    None
        The main context sections are appended to ``lines`` in place.

    Notes
    -----
    The function preserves the ranked order of ``top_matches`` and only emits
    enriched blocks for the configured leading subset.
    """
    lines.append("=== TOP MATCHES ===")
    if not top_matches:
        lines.append("No direct symbol matches found.")
    else:
        for symbol in top_matches:
            lines.append(_format_symbol(symbol, include_path=True))

    lines.append("\n=== RELATED DOCSTRING ISSUES ===")
    if not doc_issues:
        lines.append("No related docstring issues.")
    else:
        for issue_type, message in doc_issues:
            if message.startswith("Module ") and message.endswith("Missing docstring"):
                message = message.replace(
                    "Missing docstring",
                    "Missing module-level docstring",
                )
            lines.append(f"{issue_type}: {message}")

    lines.append("\n=== SUGGESTED CONTEXT ===")
    cache: dict[Path, tuple[str, list[str], ast.Module]] = {}
    for index, symbol in enumerate(top_matches[:ENRICHED_CONTEXT_LIMIT]):
        if index > 0:
            lines.append("")
        lines.extend(_format_enriched_symbol(root, symbol, cache))

    lines.append("\n=== MODULE EXPANSION ===")
    if not expanded:
        lines.append("No module expansion available.")
    else:
        for symbol in expanded:
            lines.append(_format_symbol(symbol, include_path=False))

    lines.append("\n=== CROSS-MODULE REFERENCES ===")
    if not unique_refs:
        lines.append("No cross-module references found.")
    else:
        for file_path, lineno in unique_refs:
            try:
                rel_path = str(Path(file_path).relative_to(root))
            except ValueError:
                rel_path = str(file_path)

            lines.append(f"{rel_path}:{lineno}")


def context_for(
    root: Path,
    query: str,
    *,
    prefix: str | None = None,
    as_json: bool = False,
    as_prompt: bool = False,
    explain: bool = False,
) -> str:
    """
    Build a structured context block for a given query.

    Parameters
    ----------
    root : pathlib.Path
        Root directory of the indexed repository.
    query : str
        Query string used to retrieve relevant symbols and context.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict files and references.
    as_json : bool, optional
        Whether to emit the JSON representation.
    as_prompt : bool, optional
        Whether to emit the prompt-oriented representation.
    explain : bool, optional
        Whether to include retrieval diagnostics.

    Returns
    -------
    str
        Structured text block containing:
        - top symbol matches
        - related docstring issues
        - enriched code context
        - module expansion
        - cross-module references

    Notes
    -----
    The output is optimized for LLM consumption and follows a
    deterministic section-based layout. Query classification is
    performed before retrieval and passed into the scoring phase.

    Raises
    ------
    sqlite3.Error
        If the repository index cannot be opened or queried.
    """
    normalized_prefix = normalize_prefix(root, prefix)
    conn = cast("sqlite3.Connection", active_index_backend().open_connection(root))
    intent: QueryIntent = classify_query(query)
    plan = build_retrieval_plan(intent)
    diversity: DiversityDiagnostics | None = None
    expansion: ExpansionDiagnostics | None = None
    producer_diagnostics: list[ProducerDiagnosticsEntry] | None = None
    signal_collection: SignalCollectionDiagnostics | None = None
    retrieval_signals: list[RetrievalSignal] = []
    signal_preview: list[dict[str, object]] | None = None
    signal_merge: list[dict[str, object]] | None = None

    # --- PHASE 1+2: candidate retrieval + scoring ---
    bundles = _build_channel_bundles(
        root,
        query,
        conn,
        intent,
        plan,
        normalized_prefix,
    )

    ordered_channels: list[ChannelName] | None = [
        name for name, _ in _get_channel_functions(plan)
    ]
    assert ordered_channels is not None
    channel_producers = _channel_retrieval_producers(ordered_channels)

    if explain:
        enabled = _enabled_channels(plan)
        priority = _channel_priority(plan)
        retrieval_producers = channel_producers + selected_enrichment_producers(
            include_issue_annotations=_is_issue_query(query) or plan.include_doc_issues,
            include_references=plan.include_references,
            include_include_graph=plan.include_include_graph,
        )
        producer_diagnostics = _producer_diagnostics(retrieval_producers)
        retrieval_signals, signal_collection = _collect_retrieval_signals(
            bundles,
            producers=retrieval_producers,
        )
    else:
        enabled = None
        priority = None
        retrieval_signals, _signal_collection = _collect_retrieval_signals(
            bundles,
            producers=channel_producers,
        )

    ranked_merged, provenance = _rank_signals_with_provenance(
        retrieval_signals,
        intent=intent,
    )
    if explain:
        top_matches, diversity = _diversify_merged_symbols_explain(
            [symbol for symbol, _score in ranked_merged]
        )
    else:
        top_matches = _diversify_merged_symbols(
            [symbol for symbol, _score in ranked_merged]
        )
        ordered_channels = None

    # --- PHASE 2B: issue-driven candidate enrichment ---
    if _is_issue_query(query):
        for symbol in _issue_driven_symbols(
            root,
            query,
            conn,
            prefix=normalized_prefix,
        ):
            if symbol not in top_matches:
                top_matches.append(symbol)

    top_matches = top_matches[:10]

    # --- PHASE 2C: remove module entries
    # if same module already represented by functions ---
    modules_with_functions = {
        module for t, module, name, _, _ in top_matches if t != "module"
    }

    filtered_matches: list[SymbolRow] = []

    for sym in top_matches:
        t, module, _, _, _ = sym
        if t == "module" and module in modules_with_functions:
            continue
        filtered_matches.append(sym)

    top_matches = filtered_matches
    confidence_map: dict[SymbolRow, float] = {}

    if not top_matches:
        if as_json:
            result = _render_context(
                root,
                query,
                [],
                [],
                [],
                [],
                as_json=True,
                explain=explain,
                diversity=diversity,
                expansion=expansion,
                plan=plan,
                producers=producer_diagnostics,
                signal_collection=signal_collection,
                signal_preview=signal_preview,
                signal_merge=signal_merge,
            )
            conn.close()
            return result

        if as_prompt:
            result = _render_context(
                root,
                query,
                [],
                [],
                [],
                [],
                as_prompt=True,
                explain=explain,
                diversity=diversity,
                expansion=expansion,
                plan=plan,
                producers=producer_diagnostics,
                signal_collection=signal_collection,
                signal_preview=signal_preview,
                signal_merge=signal_merge,
            )
            conn.close()
            return result

        conn.close()
        return "No relevant matches found."

    graph_retrieval_signals = _collect_graph_retrieval_signals(
        GraphRetrievalRequest(
            root=root,
            top_matches=top_matches,
            conn=conn,
            include_include_graph=plan.include_include_graph,
            include_references=plan.include_references,
            prefix=normalized_prefix,
        )
    )
    if graph_retrieval_signals:
        retrieval_signals = sorted(
            [*retrieval_signals, *graph_retrieval_signals],
            key=signal_sort_key,
        )
        ranked_merged, provenance = _rank_signals_with_provenance(
            retrieval_signals,
            intent=intent,
        )
        if explain:
            top_matches, diversity = _diversify_merged_symbols_explain(
                [symbol for symbol, _score in ranked_merged]
            )
        else:
            top_matches = _diversify_merged_symbols(
                [symbol for symbol, _score in ranked_merged]
            )

    # --- confidence estimation (lightweight, deterministic) ---
    query_tokens = list(_tokenize(query))

    for rank, symbol in enumerate(top_matches):
        base = 1.0 - (rank / max(len(top_matches), 1))
        name = symbol[2].lower()
        overlap = sum(1 for t in query_tokens if t in name)

        confidence = base + (0.1 * overlap)

        confidence = min(confidence, 1.0)

        confidence_map[symbol] = confidence

    # --- PHASE 3: related docstring issues ---
    if plan.include_doc_issues:
        doc_issues, related_symbols = _collect_doc_issues_and_related(
            root,
            query,
            top_matches,
            conn,
            prefix=normalized_prefix,
        )
    else:
        doc_issues, related_symbols = [], []

    doc_issues = doc_issues[:MAX_ISSUES]

    for match in related_symbols:
        if match not in top_matches:
            top_matches.append(match)

    top_matches = top_matches[:10]

    # --- PHASE 4+5: module expansion + references ---
    expanded, unique_refs, expansion = _expand_and_collect_references(
        root,
        top_matches,
        conn,
        include_include_graph=plan.include_include_graph,
        include_references=plan.include_references,
        prefix=normalized_prefix,
    )

    if explain and signal_collection is not None:
        used_producers = list(cast("list[str]", signal_collection["used_producers"]))
        ignored_producers = list(
            cast("list[str]", signal_collection["ignored_producers"])
        )
        graph_producers = sorted(
            {
                signal.producer_name
                for signal in retrieval_signals
                if signal.family == "graph"
            }
        )
        used_set = set(used_producers)
        ignored_set = set(ignored_producers)
        for producer_name in graph_producers:
            used_set.add(producer_name)
            ignored_set.discard(producer_name)
        signal_collection = _signal_collection_diagnostics(
            sorted(retrieval_signals, key=signal_sort_key),
            used_producers=sorted(used_set),
            ignored_producers=sorted(ignored_set),
        )
        signal_preview = _signal_preview(retrieval_signals)
        signal_merge = _signal_summary_by_symbol(retrieval_signals, top_matches)

    # --- PHASE 6: rendering ---
    result = _render_context(
        root,
        query,
        top_matches,
        doc_issues,
        expanded,
        unique_refs,
        confidence_map=confidence_map,
        as_json=as_json,
        as_prompt=as_prompt,
        explain=explain,
        intent=intent,
        plan=plan,
        enabled_channels=enabled,
        channel_priority=priority,
        ordered_channels=ordered_channels,
        producers=producer_diagnostics,
        signal_collection=signal_collection,
        signal_preview=signal_preview,
        signal_merge=signal_merge,
        bundles=bundles if explain else None,
        provenance=provenance if explain else None,
        diversity=diversity if explain else None,
        expansion=expansion if explain else None,
    )
    conn.close()
    return result


__version__ = package_version()
