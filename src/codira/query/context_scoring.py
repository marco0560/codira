"""Focused context-query responsibility module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.config import DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES
from codira.prefix import prefix_clause
from codira.query.context_models import (
    _MIN_SCORE,
    CHANNEL_WEIGHTS,
    DISPLAY_DOCSTRING_LINE_LIMIT,
    FALLBACK_SYMBOL_AGGREGATION_RULES,
    MERGE_CROSS_FAMILY_BONUS,
    MERGE_LANGUAGE_CAPS,
    MERGE_MAX_PER_FILE,
    MERGE_RESULT_LIMIT,
    MERGE_ROLE_CAPS,
    PRIMARY_SYMBOL_AGGREGATION_RULES,
    SYMBOL_FALLBACK_SCAN_LIMIT,
    SYMBOL_TERM_MATCH_LIMIT,
    CandidateSignalValue,
    DeferralReason,
    DiversityDiagnostics,
    DiversityEntry,
    FileRole,
    MergeDiagnostics,
    MergeDiagnosticsEntry,
    SelectionStage,
    SignalAggregationRule,
    _DiversitySelectionPolicy,
    _DiversitySelectionState,
)
from codira.query.context_source import (
    _classify_file_role,
    _documentation_docs_path_bonus,
    _extract_code_context,
    _file_role_bias,
    _path_bias,
    _scored_symbol_sort_key,
    _symbol_sort_key,
    _tokenize,
)
from codira.query.exact import find_symbol
from codira.query.signals import (
    RetrievalSignal,
    RetrievalSignalFamily,
    RetrievalSignalKind,
    signal_sort_key,
)
from codira.version import package_version

if TYPE_CHECKING:
    from codira.contracts import BackendQueryConnection
    from codira.query.classifier import QueryIntent
    from codira.types import (
        ChannelBundle,
        ChannelName,
        ChannelResults,
        DocumentationRow,
        SymbolRow,
    )


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
    signals = _candidate_retrieval_signals(
        query_tokens,
        symbol,
        intent=intent,
    )
    return _aggregate_candidate_signals(signals, PRIMARY_SYMBOL_AGGREGATION_RULES)


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


def _backend_row_int(value: object) -> int:
    """
    Coerce one backend query row value into a deterministic line number.

    Parameters
    ----------
    value : object
        Backend-native row value for an integer column.

    Returns
    -------
    int
        Integer line number extracted from the backend row value.
    """
    return int(cast("str | bytes | bytearray | int", value))


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


def _candidate_signal_values(
    query_tokens: list[str],
    symbol: SymbolRow,
    *,
    intent: QueryIntent | None = None,
    raw_query: str | None = None,
    target_symbol: str | None = None,
) -> tuple[CandidateSignalValue, ...]:
    """
    Extract deterministic signal values for one symbol candidate.

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
    tuple[CandidateSignalValue, ...]
        Extracted signal values consumed by core aggregation rules.
    """
    symbol_type, module_name, name, file_path, _lineno = symbol
    normalized_query = " ".join(query_tokens)
    symbol_name = name
    module_tokens = set(_tokenize(module_name))
    name_tokens = set(_tokenize(symbol_name))
    normalized_strong_tokens = _normalized_strong_query_tokens(query_tokens)

    lexical_kind: RetrievalSignalKind = "text_match"
    lexical_family: RetrievalSignalFamily = "lexical"
    task_kind: RetrievalSignalKind = "proximity"
    task_family: RetrievalSignalFamily = "task"

    return (
        CandidateSignalValue(
            "exact_name_match",
            int(normalized_query == symbol_name),
            "exact_symbol",
            lexical_family,
        ),
        CandidateSignalValue(
            "substring_name_match",
            int(
                normalized_query != symbol_name
                and bool(normalized_query in symbol_name)
            ),
            lexical_kind,
            lexical_family,
        ),
        CandidateSignalValue(
            "name_token_overlap_count",
            len(set(query_tokens) & name_tokens),
            lexical_kind,
            lexical_family,
        ),
        CandidateSignalValue(
            "module_token_overlap_count",
            len(set(query_tokens) & module_tokens),
            lexical_kind,
            lexical_family,
        ),
        CandidateSignalValue(
            "is_function",
            int(symbol_type == "function"),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "is_private",
            int(symbol_name.startswith("_")),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "path_bias",
            _path_bias(file_path, module_name, intent=intent),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "query_targets_module_as_module",
            int("module" in query_tokens and symbol_type == "module"),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "query_targets_module_as_non_module",
            int("module" in query_tokens and symbol_type != "module"),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "module_depth_penalty_count",
            module_name.count(".") if symbol_type == "module" else 0,
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "exact_target_symbol_match",
            int(target_symbol is not None and symbol_name == target_symbol),
            "exact_symbol",
            lexical_family,
        ),
        CandidateSignalValue(
            "exact_raw_query_match",
            int(raw_query is not None and symbol_name == raw_query),
            "exact_symbol",
            lexical_family,
        ),
        CandidateSignalValue(
            "lexical_frequency_count",
            sum(1 for token in query_tokens if token in symbol_name.lower()),
            lexical_kind,
            lexical_family,
        ),
        CandidateSignalValue(
            "implementation_module_bonus",
            int(
                not module_name.startswith("tests.")
                and not module_name.startswith("scripts.")
            ),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "lowered_module_penalty",
            int(any(x in module_name.lower() for x in ("cli", "scanner", "storage"))),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "identifier_exact_match",
            int(
                bool(
                    intent and intent.is_identifier_query and symbol_name == intent.raw
                )
            ),
            "exact_symbol",
            lexical_family,
        ),
        CandidateSignalValue(
            "identifier_module_suffix_match",
            int(
                bool(
                    intent
                    and intent.is_identifier_query
                    and module_name.endswith(intent.raw)
                    and symbol_name != intent.raw
                )
            ),
            lexical_kind,
            lexical_family,
        ),
        CandidateSignalValue(
            "multi_term_module_bonus",
            int(bool(intent and intent.is_multi_term and symbol_type == "module")),
            task_kind,
            task_family,
        ),
        CandidateSignalValue(
            "strong_token_hit",
            int(
                any(
                    token in _tokenize(symbol_name)
                    for token in normalized_strong_tokens
                )
            ),
            lexical_kind,
            lexical_family,
        ),
    )


def _candidate_retrieval_signals(
    query_tokens: list[str],
    symbol: SymbolRow,
    *,
    intent: QueryIntent | None = None,
    raw_query: str | None = None,
    target_symbol: str | None = None,
) -> list[RetrievalSignal]:
    """
    Build normalized retrieval signals for one symbol candidate.

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
    list[codira.query.signals.RetrievalSignal]
        Score-free candidate evidence signals consumed by aggregation rules.
    """
    signals: list[RetrievalSignal] = []
    for value in _candidate_signal_values(
        query_tokens,
        symbol,
        intent=intent,
        raw_query=raw_query,
        target_symbol=target_symbol,
    ):
        if value.value == 0:
            continue
        signals.append(
            RetrievalSignal(
                kind=value.kind,
                family=value.family,
                target=symbol,
                producer_name="query-channel-symbol",
                producer_version=package_version(),
                capability_name="symbol_lookup",
                capability_version="1",
                evidence_detail=value.evidence_detail,
                channel_name="symbol",
                strength=float(value.value),
            )
        )

    return sorted(signals, key=signal_sort_key)


def _candidate_signal_strength(
    signals: list[RetrievalSignal], evidence_detail: str
) -> float:
    """
    Sum signal strength for one candidate evidence detail.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Candidate retrieval signals.
    evidence_detail : str
        Evidence detail to aggregate.

    Returns
    -------
    float
        Total strength for matching signals.
    """
    return sum(
        signal.strength if signal.strength is not None else 0.0
        for signal in signals
        if signal.evidence_detail == evidence_detail
    )


def _aggregate_candidate_signals(
    signals: list[RetrievalSignal],
    rules: tuple[SignalAggregationRule, ...],
) -> int:
    """
    Apply core aggregation policy to candidate retrieval signals.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Score-free candidate evidence signals.
    rules : tuple[SignalAggregationRule, ...]
        Ordered aggregation rules to apply.

    Returns
    -------
    int
        Total deterministic score contribution from the supplied rules.
    """
    return int(
        sum(
            _candidate_signal_strength(signals, rule.evidence_detail) * rule.weight
            for rule in rules
        )
    )


def _candidate_has_signal(signals: list[RetrievalSignal], evidence_detail: str) -> bool:
    """
    Return whether a candidate emitted one named evidence signal.

    Parameters
    ----------
    signals : list[codira.query.signals.RetrievalSignal]
        Candidate retrieval signals.
    evidence_detail : str
        Evidence detail to look for.

    Returns
    -------
    bool
        ``True`` when any signal carries the requested evidence detail.
    """
    return any(signal.evidence_detail == evidence_detail for signal in signals)


def _is_documentation_symbol(symbol: SymbolRow) -> bool:
    """
    Return whether a symbol-shaped row represents documentation retrieval.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Symbol-shaped top-match row.

    Returns
    -------
    bool
        ``True`` when the row came from the documentation channel.
    """
    return symbol[0] == "documentation"


def _documentation_symbol(documentation: DocumentationRow) -> SymbolRow:
    """
    Convert one documentation artifact row into a top-match row.

    Parameters
    ----------
    documentation : codira.types.DocumentationRow
        Documentation candidate row returned by a backend.

    Returns
    -------
    codira.types.SymbolRow
        Symbol-shaped row with explicit documentation provenance.
    """
    (
        _stable_id,
        kind,
        source_format,
        file_path,
        lineno,
        _end_lineno,
        title,
        _heading_path,
        _text,
    ) = documentation
    display_title = title if title else kind
    return ("documentation", source_format, display_title, file_path, lineno)


def _format_symbol(root: Path, symbol: SymbolRow, *, include_path: bool) -> str:
    """
    Format a symbol row for human-readable output.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
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

    if _is_documentation_symbol(symbol):
        head = f"documentation: {name}:{lineno} [{module_name}]"
        if include_path:
            try:
                rel_path = str(Path(file_path).relative_to(root))
            except ValueError:
                rel_path = str(file_path)
            return f"{head} ({rel_path})"
        return head

    if symbol_type == "module":
        head = f"{symbol_type}: {module_name}:{lineno}"
    else:
        head = f"{symbol_type}: {module_name}.{name}:{lineno}"

    if include_path:
        try:
            rel_path = str(Path(file_path).relative_to(root))
        except ValueError:
            rel_path = str(file_path)
        return f"{head} ({rel_path})"
    return head


def _format_enriched_symbol(
    root: Path,
    symbol: SymbolRow,
    cache: dict[Path, tuple[str, list[str]]],
    *,
    max_source_file_bytes: int = DEFAULT_EMBEDDING_INDEX_MAX_SOURCE_FILE_BYTES,
) -> list[str]:
    """
    Format a symbol with location, snippet, and docstring details.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    symbol : codira.types.SymbolRow
        Symbol row to render.
    cache : dict[pathlib.Path, tuple[str, list[str]]]
        Source-file cache shared across multiple symbols.
    max_source_file_bytes : int, optional
        Command-scoped source-ingestion byte ceiling.

    Returns
    -------
    list[str]
        Multi-line textual block describing the symbol.
    """
    symbol_type, module_name, name, file_path, lineno = symbol
    if _is_documentation_symbol(symbol):
        try:
            rel_path = str(Path(file_path).relative_to(root))
        except ValueError:
            rel_path = str(file_path)
        return [
            f"documentation {name}",
            f"  File: {rel_path}",
            f"  Line: {lineno}",
            f"  Provenance: {module_name}",
        ]

    signature, docstring, snippet = _extract_code_context(
        root,
        symbol,
        cache,
        max_source_file_bytes=max_source_file_bytes,
    )

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


def _retrieve_symbol_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Retrieve and score symbol-channel candidates for a query.

    Parameters
    ----------
    root : pathlib.Path
        Root directory of the indexed repository.
    query : str
        User query string.
    conn : object
        Active database connection.
    intent : QueryIntent
        Structured classification of the query.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Unused similarity-index runtime profile.

    Returns
    -------
    list[tuple[float, SymbolRow]]
        Ranked candidate symbols with scores sorted by descending score.

    Notes
    -----
    This phase applies deterministic scoring only. It does not perform
    final deduplication or pruning.
    """
    del search_profile
    matches = find_symbol(root, query, prefix=prefix, conn=conn)
    query_tokens = sorted(_tokenize(query))

    candidate_map: dict[SymbolRow, None] = {match: None for match in matches}

    search_terms = sorted({token for token in query_tokens if len(token) >= 4})
    prefix_sql, prefix_params = prefix_clause(prefix, "f.path")

    for term in search_terms:
        rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
                _backend_row_int(row[4]),
            )
            candidate_map[candidate] = None

    if candidate_map:
        all_candidates = sorted(
            candidate_map,
            key=lambda symbol: (symbol[1], symbol[2], symbol[3], symbol[4]),
        )
    else:
        rows = conn.execute(  # nosemgrep: python.sqlalchemy.security.sqlalchemy-execute-raw-query.sqlalchemy-execute-raw-query
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
            (str(t), str(m), str(n), str(f), _backend_row_int(lin))
            for t, m, n, f, lin in rows
        ]

    target_symbol = _extract_target_symbol(query_tokens)
    scored: list[tuple[float, SymbolRow]] = []

    for candidate in all_candidates:
        signals = _candidate_retrieval_signals(
            query_tokens,
            candidate,
            intent=intent,
            raw_query=query,
            target_symbol=target_symbol,
        )
        if not _candidate_has_signal(signals, "strong_token_hit"):
            continue
        score = _aggregate_candidate_signals(signals, PRIMARY_SYMBOL_AGGREGATION_RULES)
        if score >= _MIN_SCORE:
            scored.append((float(score), candidate))

    scored.sort(key=_scored_symbol_sort_key)

    if not scored:
        fallback_scored: list[tuple[float, SymbolRow]] = []

        for candidate in all_candidates:
            signals = _candidate_retrieval_signals(
                query_tokens,
                candidate,
                intent=intent,
            )
            score = _aggregate_candidate_signals(
                signals,
                FALLBACK_SYMBOL_AGGREGATION_RULES,
            )
            fallback_scored.append((float(score), candidate))

        fallback_scored.sort(key=_scored_symbol_sort_key)
        return fallback_scored

    return scored


def _retrieve_test_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Retrieve candidates for the test channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Unused similarity-index runtime profile.

    Returns
    -------
    codira.types.ChannelResults
        Empty channel results. Test-specific retrieval is not implemented.
    """
    del root, query, conn, intent, prefix, search_profile
    return []


def _retrieve_script_candidates(  # noqa: PLR0913
    root: Path,
    query: str,
    conn: BackendQueryConnection,
    intent: QueryIntent,
    prefix: str | None,
    search_profile: str | None,
) -> ChannelResults:
    """
    Retrieve candidates for the script channel.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing indexed files.
    query : str
        User query string.
    conn : object
        Open database connection.
    intent : codira.query.classifier.QueryIntent
        Structured query classification.
    prefix : str | None
        Absolute normalized prefix used to restrict candidate files.
    search_profile : str | None
        Unused similarity-index runtime profile.

    Returns
    -------
    codira.types.ChannelResults
        Empty channel results. Script-specific retrieval is not implemented.
    """
    del root, query, conn, intent, prefix, search_profile
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
    top_symbols = _diversify_merged_symbols(
        [symbol for symbol, _ in ranked],
        intent=intent,
    )

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
    from codira.query.context_channels import (
        _channel_retrieval_producers,
        _collect_retrieval_signals,
    )

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

        weight = _channel_weight_for_intent(
            channel_name,
            intent,
            default=weights.get(channel_name, 1.0),
        )
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
        docs_path_bonus = _documentation_docs_path_bonus(symbol, symbol_channel_scores)
        merge_score = rrf_score + evidence_bonus + role_bonus + docs_path_bonus
        winner = max(
            sorted(symbol_channel_scores.items()),
            key=lambda item: item[1],
        )[0]
        diagnostics_entry: MergeDiagnosticsEntry = {
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
        if docs_path_bonus:
            diagnostics_entry["docs_path_bonus"] = docs_path_bonus
        diagnostics[symbol] = diagnostics_entry
        ranked_with_scores.append((symbol, merge_score))

    ranked = sorted(
        ranked_with_scores,
        key=lambda item: (-item[1], *_symbol_sort_key(item[0])),
    )
    return ranked, diagnostics


def _should_defer_documentation_for_code_quota(
    *,
    enforce_quota: bool,
    is_documentation: bool,
    selected_docs_count: int,
    selected_code_count: int,
) -> bool:
    """
    Return whether a documentation result would violate docs/code parity.

    Parameters
    ----------
    enforce_quota : bool
        Whether the active query intent requires docs/code quota enforcement.
    is_documentation : bool
        Whether the candidate is a documentation-shaped result.
    selected_docs_count : int
        Number of already selected documentation results.
    selected_code_count : int
        Number of already selected non-documentation results.

    Returns
    -------
    bool
        ``True`` when appending the documentation result would make code less
        than half of the selected result set.
    """
    return (
        enforce_quota
        and is_documentation
        and selected_docs_count >= selected_code_count
    )


def _diversity_diagnostic_entry(
    symbol: SymbolRow,
    *,
    role: FileRole,
    language: str,
    selection_stage: SelectionStage | None = None,
    reason: DeferralReason | None = None,
) -> DiversityEntry:
    """
    Build one deterministic diversity diagnostic entry.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Candidate row being described.
    role : {"implementation", "interface", "test", "tooling", "other"}
        Classified file role.
    language : str
        Classified language family.
    selection_stage : {"primary", "deferred"} | None, optional
        Selection pass that accepted the candidate.
    reason : str | None, optional
        Deferral reason when the candidate was not accepted in the primary pass.

    Returns
    -------
    dict[str, object]
        Stable explain-mode diversity diagnostic entry.
    """
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


def _try_append_diversified_symbol(
    state: _DiversitySelectionState,
    symbol: SymbolRow,
    *,
    selection_stage: SelectionStage,
    policy: _DiversitySelectionPolicy,
) -> bool:
    """
    Try to append one ranked symbol under diversity and docs/code quota rules.

    Parameters
    ----------
    state : codira.query.context._DiversitySelectionState
        Mutable diversity selection state.
    symbol : codira.types.SymbolRow
        Candidate row under consideration.
    selection_stage : {"primary", "deferred"}
        Current diversity selection pass.
    policy : codira.query.context._DiversitySelectionPolicy
        Immutable selection policy for quota and cap checks.

    Returns
    -------
    bool
        ``True`` when the candidate was selected.
    """
    file_path = symbol[3]
    module_name = symbol[1]
    role = _classify_file_role(file_path, module_name)
    language = _classify_file_language(file_path)
    is_documentation = symbol[0] == "documentation"

    quota_would_defer = _should_defer_documentation_for_code_quota(
        enforce_quota=policy.enforce_docs_code_quota,
        is_documentation=is_documentation,
        selected_docs_count=state.selected_docs_count,
        selected_code_count=state.selected_code_count,
    )
    if quota_would_defer and state.selected_code_count < policy.code_candidate_count:
        if selection_stage == "primary":
            state.deferred.append((symbol, "docs_code_quota"))
        return False

    if selection_stage == "deferred" and quota_would_defer:
        return False

    if state.seen_files.get(file_path, 0) >= MERGE_MAX_PER_FILE:
        if selection_stage == "primary":
            state.deferred.append((symbol, "file_cap"))
        return False

    if (
        selection_stage == "primary"
        and state.role_counts.get(role, 0) >= MERGE_ROLE_CAPS[role]
    ):
        state.deferred.append((symbol, "role_cap"))
        return False

    if (
        selection_stage == "primary"
        and policy.available_language_count > 1
        and state.language_counts.get(language, 0)
        >= MERGE_LANGUAGE_CAPS.get(
            language,
            1,
        )
    ):
        state.deferred.append((symbol, "language_cap"))
        return False

    state.selected.append(symbol)
    if is_documentation:
        state.selected_docs_count += 1
    else:
        state.selected_code_count += 1
    state.seen_files[file_path] = state.seen_files.get(file_path, 0) + 1
    state.role_counts[role] = state.role_counts.get(role, 0) + 1
    state.language_counts[language] = state.language_counts.get(language, 0) + 1
    state.selected_entries.append(
        _diversity_diagnostic_entry(
            symbol,
            role=role,
            language=language,
            selection_stage=selection_stage,
        )
    )
    return True


def _diversify_merged_symbols(
    ranked_symbols: list[SymbolRow],
    *,
    intent: QueryIntent | None = None,
) -> list[SymbolRow]:
    """
    Apply deterministic file and role caps to merged ranked symbols.

    Parameters
    ----------
    ranked_symbols : list[codira.types.SymbolRow]
        Symbols already ordered by merged ranking score.
    intent : codira.query.classifier.QueryIntent | None, optional
        Classified query intent used to enforce task-specific diversity quotas.

    Returns
    -------
    list[codira.types.SymbolRow]
        Diversified top symbols capped by file and role before truncation.
    """
    selected, _diagnostics = _diversify_merged_symbols_explain(
        ranked_symbols,
        intent=intent,
    )
    return selected


def _diversify_merged_symbols_explain(
    ranked_symbols: list[SymbolRow],
    *,
    intent: QueryIntent | None = None,
) -> tuple[list[SymbolRow], DiversityDiagnostics]:
    """
    Diversify merged symbols while collecting deterministic diagnostics.

    Parameters
    ----------
    ranked_symbols : list[codira.types.SymbolRow]
        Symbols already ordered by merged ranking score.
    intent : codira.query.classifier.QueryIntent | None, optional
        Classified query intent used to enforce task-specific diversity quotas.

    Returns
    -------
    tuple[list[codira.types.SymbolRow], codira.query.context.DiversityDiagnostics]
        Diversified symbols plus selected and deferred diagnostic entries.
    """
    available_languages = {
        _classify_file_language(symbol[3]) for symbol in ranked_symbols
    }
    code_candidate_count = sum(
        1 for symbol in ranked_symbols if symbol[0] != "documentation"
    )
    policy = _DiversitySelectionPolicy(
        enforce_docs_code_quota=bool(
            code_candidate_count
            and intent is not None
            and intent.primary_intent in {"behavior", "test"}
        ),
        code_candidate_count=code_candidate_count,
        available_language_count=len(available_languages),
    )
    state = _DiversitySelectionState()
    deferred_entries: list[DiversityEntry] = []

    for symbol in ranked_symbols:
        if len(state.selected) >= MERGE_RESULT_LIMIT:
            break
        _try_append_diversified_symbol(
            state,
            symbol,
            selection_stage="primary",
            policy=policy,
        )

    for symbol, reason in state.deferred:
        role = _classify_file_role(symbol[3], symbol[1])
        language = _classify_file_language(symbol[3])
        deferred_entries.append(
            _diversity_diagnostic_entry(
                symbol,
                role=role,
                language=language,
                reason=reason,
            )
        )

    for symbol, _reason in state.deferred:
        if len(state.selected) >= MERGE_RESULT_LIMIT:
            break
        _try_append_diversified_symbol(
            state,
            symbol,
            selection_stage="deferred",
            policy=policy,
        )

    diagnostics: DiversityDiagnostics = {
        "selected": state.selected_entries,
        "deferred": deferred_entries,
    }
    return state.selected, diagnostics


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


def _channel_weight_for_intent(
    channel_name: ChannelName,
    intent: QueryIntent | None,
    *,
    default: float,
) -> float:
    """
    Return an intent-aware channel weight.

    Parameters
    ----------
    channel_name : codira.types.ChannelName
        Retrieval channel contributing to rank fusion.
    intent : codira.query.classifier.QueryIntent | None
        Classified query intent, when available.
    default : float
        Baseline channel weight.

    Returns
    -------
    float
        Weight adjusted for documentation-oriented query families.
    """
    if channel_name != "docs" or intent is None:
        return default
    if intent.primary_intent in {"architecture", "configuration", "api_surface"}:
        return 1.15
    if intent.primary_intent == "test":
        return 0.15
    return 0.25


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
    if channel_name in {"embedding", "semantic", "docs"}:
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
