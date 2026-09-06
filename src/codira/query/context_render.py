"""Focused context-query responsibility module."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from codira.prompts.default import PromptBuildRequest, build_prompt
from codira.query.context_models import (
    ENRICHED_CONTEXT_LIMIT,
    MAX_TOKENS,
    MERGE_LANGUAGE_CAPS,
    MERGE_MAX_PER_FILE,
    MERGE_ROLE_CAPS,
    SCHEMA_VERSION,
    ContextJsonRenderRequest,
    ContextRenderRequest,
    ExplainSectionsRequest,
    MainContextSectionsRequest,
    MergeDiagnostics,
    PromptRenderRequest,
)
from codira.query.context_scoring import (
    _format_enriched_symbol,
    _format_symbol,
)
from codira.query.context_source import (
    _classify_file_role,
    _file_role_bias,
)
from codira.semantic.embeddings import get_embedding_backend
from codira.semantic.search import (
    similarity_candidate_provenance_payload,
    similarity_query_provenance_payload,
)
from codira.version import package_version

if TYPE_CHECKING:
    from codira.query.classifier import QueryIntent, RetrievalPlan
    from codira.types import ChannelBundle, SymbolRow


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
    request: PromptRenderRequest,
) -> str:
    """
    Render the agent prompt variant of the query context.

    Parameters
    ----------
    request : PromptRenderRequest
        Prompt-render request.

    Returns
    -------
    str
        Prompt-formatted query context.
    """
    return build_prompt(
        PromptBuildRequest(
            root=request.root,
            query=request.query,
            top_matches=request.top_matches,
            doc_issues=request.doc_issues,
            expanded=request.expanded,
            unique_refs=request.unique_refs,
            prompt_symbol_line=_prompt_symbol_line,
            format_enriched_symbol=partial(
                _format_enriched_symbol,
                max_source_file_bytes=request.max_source_file_bytes,
            ),
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


def _context_blocks_payload(
    root: Path,
    top_matches: list[SymbolRow],
    *,
    max_source_file_bytes: int,
) -> list[list[str]]:
    """
    Build bounded enriched context blocks for JSON rendering.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    max_source_file_bytes : int
        Command-scoped source-ingestion byte ceiling.

    Returns
    -------
    list[list[str]]
        Token-capped enriched context blocks.
    """
    context_blocks: list[list[str]] = []
    current_tokens = 0

    for symbol in top_matches[:ENRICHED_CONTEXT_LIMIT]:
        block = _format_enriched_symbol(
            root,
            symbol,
            {},
            max_source_file_bytes=max_source_file_bytes,
        )
        block_tokens = _approx_token_count(block)
        if current_tokens + block_tokens > MAX_TOKENS:
            break
        context_blocks.append(block)
        current_tokens += block_tokens

    return context_blocks


def _top_matches_payload(
    top_matches: list[SymbolRow],
    confidence_map: dict[SymbolRow, float] | None,
) -> list[dict[str, object]]:
    """
    Serialize top matches for JSON context output.

    Parameters
    ----------
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    confidence_map : dict[codira.types.SymbolRow, float] | None
        Confidence values keyed by symbol.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable top-match rows.
    """
    rows: list[dict[str, object]] = []
    for symbol_type, module_name, name, file_path, lineno in top_matches:
        row: dict[str, object] = {
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "file": file_path,
            "lineno": lineno,
            "confidence": (
                confidence_map.get(
                    (symbol_type, module_name, name, file_path, lineno), 1.0
                )
                if confidence_map
                else 1.0
            ),
        }
        if symbol_type == "documentation":
            row["source_format"] = module_name
            row["provenance"] = module_name
        rows.append(row)
    return rows


def _module_expansion_payload(
    expanded: list[SymbolRow],
) -> list[dict[str, object]]:
    """
    Serialize expanded module symbols for JSON context output.

    Parameters
    ----------
    expanded : list[codira.types.SymbolRow]
        Secondary symbols collected by module expansion.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable expansion rows.
    """
    return [
        {
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "file": file_path,
            "lineno": lineno,
        }
        for symbol_type, module_name, name, file_path, lineno in expanded
    ]


def _channel_results_payload(
    bundles: list[ChannelBundle],
) -> dict[str, list[dict[str, object]]]:
    """
    Serialize per-channel ranked results for explain-mode JSON output.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Raw channel results.

    Returns
    -------
    dict[str, list[dict[str, object]]]
        Per-channel JSON rows capped to the leading five results.
    """
    channel_results: dict[str, list[dict[str, object]]] = {}

    for channel_name, channel in bundles:
        rows: list[dict[str, object]] = []
        resolved = getattr(channel, "resolved", ())
        for position, (
            score,
            (symbol_type, module_name, name, file_path, lineno),
        ) in enumerate(channel[:5]):
            row: dict[str, object] = {
                "type": symbol_type,
                "module": module_name,
                "name": name,
                "file": file_path,
                "lineno": lineno,
                "score": round(score, 2),
            }
            if symbol_type == "documentation":
                row["source_format"] = module_name
                row["provenance"] = module_name
            if position < len(resolved):
                row["similarity"] = similarity_candidate_provenance_payload(
                    resolved[position].candidate
                )
            rows.append(row)
        channel_results[channel_name] = rows

    return channel_results


def _similarity_channel_payload(
    bundles: list[ChannelBundle],
) -> dict[str, dict[str, object]]:
    """Serialize typed similarity query provenance retained by context channels.

    Parameters
    ----------
    bundles : list[codira.types.ChannelBundle]
        Raw channels collected before merge and diversification.

    Returns
    -------
    dict[str, dict[str, object]]
        Credential-free query provenance keyed by channels that used similarity.
    """

    payload: dict[str, dict[str, object]] = {}
    for channel_name, channel in bundles:
        search_result = getattr(channel, "search_result", None)
        if search_result is not None:
            payload[channel_name] = similarity_query_provenance_payload(search_result)
    return payload


def _merge_explain_payload(
    top_matches: list[SymbolRow],
    provenance: MergeDiagnostics,
    intent: QueryIntent | None,
) -> list[dict[str, object]]:
    """
    Serialize merge diagnostics for explain-mode JSON output.

    Parameters
    ----------
    top_matches : list[codira.types.SymbolRow]
        Primary ranked symbols.
    provenance : codira.query.context.MergeDiagnostics
        Merge diagnostics for ranked symbols.
    intent : codira.query.classifier.QueryIntent | None
        Structured query classification.

    Returns
    -------
    list[dict[str, object]]
        JSON-serializable merge diagnostics for the selected symbols.
    """
    merge_entries: list[dict[str, object]] = []

    for symbol in top_matches:
        merge_details = provenance.get(symbol)
        if not merge_details:
            continue

        symbol_type, module_name, name, _file_path, lineno = symbol
        role = _classify_file_role(symbol[3], module_name)
        role_bias = _file_role_bias(role, intent)
        entry: dict[str, object] = {
            "type": symbol_type,
            "module": module_name,
            "name": name,
            "lineno": lineno,
            "channels": cast("dict[str, float]", merge_details["channels"]),
            "families": cast("dict[str, float]", merge_details["families"]),
            "rrf_score": round(cast("float", merge_details["rrf_score"]), 4),
            "evidence_bonus": round(
                cast("float", merge_details["evidence_bonus"]),
                4,
            ),
            "role_bonus": round(cast("float", merge_details["role_bonus"]), 4),
            "merge_score": round(cast("float", merge_details["merge_score"]), 4),
            "winner": cast("str", merge_details["winner"]),
            "role": role,
            "role_bias": role_bias,
        }
        if symbol_type == "documentation":
            entry["source_format"] = module_name
            entry["provenance"] = module_name
        merge_entries.append(entry)

    return merge_entries


def _context_environment_payload(root: Path) -> dict[str, object]:
    """
    Build the stable environment subsection for JSON explain output.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose repo-local embedding configuration should be
        reported.

    Returns
    -------
    dict[str, object]
        JSON-serializable environment metadata.
    """
    embedding_backend = get_embedding_backend(root=root)
    return {
        "codira_version": package_version(),
        "schema_version": SCHEMA_VERSION,
        "embedding_backend": {
            "name": embedding_backend.name,
            "version": embedding_backend.version,
            "dim": embedding_backend.dim,
        },
    }


def _intent_explain_payload(intent: QueryIntent) -> dict[str, object]:
    """
    Serialize one classified query intent for explain output.

    Parameters
    ----------
    intent : QueryIntent
        Structured query classification.

    Returns
    -------
    dict[str, object]
        JSON-serializable intent payload.
    """
    return {
        "is_identifier_query": intent.is_identifier_query,
        "is_test_related": intent.is_test_related,
        "is_script_related": intent.is_script_related,
        "is_multi_term": intent.is_multi_term,
        "primary_intent": intent.primary_intent,
        "raw": intent.raw,
    }


def _planner_explain_payload(plan: RetrievalPlan) -> dict[str, object]:
    """
    Serialize one retrieval plan for explain output.

    Parameters
    ----------
    plan : RetrievalPlan
        Deterministic retrieval plan derived from query intent.

    Returns
    -------
    dict[str, object]
        JSON-serializable planner payload.
    """
    return {
        "primary_intent": plan.primary_intent,
        "channels": list(plan.channels),
        "include_doc_issues": plan.include_doc_issues,
        "include_include_graph": plan.include_include_graph,
        "include_references": plan.include_references,
    }


def _update_optional_explain_payload(
    explain_block: dict[str, object],
    request: ContextJsonRenderRequest,
) -> None:
    """
    Merge optional explain sections into the JSON explain payload.

    Parameters
    ----------
    explain_block : dict[str, object]
        Mutable explain payload under construction.
    request : ContextJsonRenderRequest
        JSON render request carrying optional explain metadata.

    Returns
    -------
    None
        Optional sections are added to ``explain_block`` in place.
    """
    optional_sections: list[tuple[str, object | None]] = [
        (
            "enabled_channels",
            (
                sorted(request.enabled_channels)
                if request.enabled_channels is not None
                else None
            ),
        ),
        ("channel_priority", request.channel_priority),
        ("ordered_channels", request.ordered_channels),
        ("retrieval_producers", request.producers),
        ("signal_collection", request.signal_collection),
        ("signals", request.signal_preview),
        ("signal_merge", request.signal_merge),
        (
            "channel_results",
            (
                _channel_results_payload(request.bundles)
                if request.bundles is not None
                else None
            ),
        ),
        (
            "similarity",
            (
                _similarity_channel_payload(request.bundles)
                if request.bundles is not None
                else None
            ),
        ),
        (
            "merge",
            (
                _merge_explain_payload(
                    request.top_matches,
                    request.provenance,
                    request.intent,
                )
                if request.provenance is not None
                else None
            ),
        ),
        ("diversity", request.diversity),
        ("expansion", request.expansion),
    ]
    for key, value in optional_sections:
        if value is not None:
            explain_block[key] = value


def _context_explain_payload(
    request: ContextJsonRenderRequest,
) -> dict[str, object]:
    """
    Build the explain block for JSON context output.

    Parameters
    ----------
    request : ContextJsonRenderRequest
        JSON render request carrying explain-mode metadata.

    Returns
    -------
    dict[str, object]
        JSON-serializable explain block.
    """
    explain_block: dict[str, object] = {
        "environment": _context_environment_payload(request.root)
    }

    if request.intent:
        explain_block["intent"] = _intent_explain_payload(request.intent)
    if request.plan is not None:
        explain_block["planner"] = _planner_explain_payload(request.plan)
    _update_optional_explain_payload(explain_block, request)
    return explain_block


def _render_context_json(
    request: ContextJsonRenderRequest,
) -> str:
    """
    Render context output as structured JSON.

    Parameters
    ----------
    request : ContextJsonRenderRequest
        JSON render request.

    Returns
    -------
    str
        JSON-encoded context payload.
    """
    status = "ok" if request.top_matches else "no_matches"

    result: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "top_matches": _top_matches_payload(
            request.top_matches,
            request.confidence_map,
        ),
        "doc_issues": [
            {"type": issue_type, "message": message}
            for issue_type, message in request.doc_issues
        ],
        "context": _context_blocks_payload(
            request.root,
            request.top_matches,
            max_source_file_bytes=request.max_source_file_bytes,
        ),
        "module_expansion": _module_expansion_payload(request.expanded),
        "references": [
            {"file": file_path, "lineno": lineno}
            for file_path, lineno in request.unique_refs
        ],
    }

    if request.explain:
        result["explain"] = _context_explain_payload(request)

    return json.dumps(result, indent=2)


def _render_context_prompt(
    request: PromptRenderRequest,
) -> str:
    """
    Render context output in prompt form.

    Parameters
    ----------
    request : PromptRenderRequest
        Prompt-render request.

    Returns
    -------
    str
        Prompt-formatted query context.
    """
    return _render_agent_prompt(request)


def _render_context(
    request: ContextRenderRequest,
) -> str:
    """
    Render final structured context output.

    Parameters
    ----------
    request : ContextRenderRequest
        Final context render request.

    Returns
    -------
    str
        Rendered context in plain-text, JSON, or prompt form.
    """
    if request.as_json:
        return _render_context_json(
            ContextJsonRenderRequest(
                root=request.root,
                top_matches=request.top_matches,
                doc_issues=request.doc_issues,
                expanded=request.expanded,
                unique_refs=request.unique_refs,
                max_source_file_bytes=request.max_source_file_bytes,
                confidence_map=request.confidence_map,
                explain=request.explain,
                intent=request.intent,
                plan=request.plan,
                enabled_channels=request.enabled_channels,
                channel_priority=request.channel_priority,
                ordered_channels=request.ordered_channels,
                producers=request.producers,
                signal_collection=request.signal_collection,
                signal_preview=request.signal_preview,
                signal_merge=request.signal_merge,
                bundles=request.bundles,
                provenance=request.provenance,
                diversity=request.diversity,
                expansion=request.expansion,
            )
        )

    if request.as_prompt:
        return _render_context_prompt(
            PromptRenderRequest(
                root=request.root,
                query=request.query,
                top_matches=request.top_matches,
                doc_issues=request.doc_issues,
                expanded=request.expanded,
                unique_refs=request.unique_refs,
                max_source_file_bytes=request.max_source_file_bytes,
            )
        )

    lines: list[str] = []

    if request.explain:
        _append_explain_sections(
            ExplainSectionsRequest(
                lines=lines,
                explain=request.explain,
                intent=request.intent,
                plan=request.plan,
                enabled_channels=request.enabled_channels,
                channel_priority=request.channel_priority,
                ordered_channels=request.ordered_channels,
                producers=request.producers,
                signal_collection=request.signal_collection,
                signal_preview=request.signal_preview,
                signal_merge=request.signal_merge,
                bundles=request.bundles,
                provenance=request.provenance,
                diversity=request.diversity,
                expansion=request.expansion,
                top_matches=request.top_matches,
                root=request.root,
            )
        )

    _append_main_context_sections(
        MainContextSectionsRequest(
            lines=lines,
            root=request.root,
            top_matches=request.top_matches,
            doc_issues=request.doc_issues,
            expanded=request.expanded,
            unique_refs=request.unique_refs,
            max_source_file_bytes=request.max_source_file_bytes,
        )
    )

    return "\n".join(lines)


def _append_explain_environment(
    request: ExplainSectionsRequest,
) -> None:
    """
    Append explain environment, intent, and routing sections.

    Parameters
    ----------
    request : ExplainSectionsRequest
        Explain-section render request.

    Returns
    -------
    None
        Environment, intent, and routing sections are appended in place.
    """
    embedding_backend = get_embedding_backend(root=request.root)
    request.lines.append("=== EXPLAIN: ENVIRONMENT ===")
    request.lines.append(f"codira_version: {package_version()}")
    request.lines.append(f"schema_version: {SCHEMA_VERSION}")
    request.lines.append(
        "embedding_backend: "
        f"{embedding_backend.name}"
        f" version={embedding_backend.version}"
        f" dim={embedding_backend.dim}"
    )
    request.lines.append("")
    request.lines.append("=== EXPLAIN: QUERY INTENT ===")
    if request.intent:
        request.lines.append(
            f"is_identifier_query: {request.intent.is_identifier_query}"
        )
        request.lines.append(f"is_test_related: {request.intent.is_test_related}")
        request.lines.append(f"is_script_related: {request.intent.is_script_related}")
        request.lines.append(f"is_multi_term: {request.intent.is_multi_term}")
        request.lines.append(f"primary_intent: {request.intent.primary_intent}")
        request.lines.append(f"raw: {request.intent.raw}")

    request.lines.append("\n=== EXPLAIN: CHANNEL ROUTING ===")
    if request.plan is not None:
        request.lines.append(f"planner.primary_intent: {request.plan.primary_intent}")
        request.lines.append(f"planner.channels: {list(request.plan.channels)}")
        request.lines.append(
            f"planner.include_doc_issues: {request.plan.include_doc_issues}"
        )
        request.lines.append(
            f"planner.include_include_graph: {request.plan.include_include_graph}"
        )
        request.lines.append(
            f"planner.include_references: {request.plan.include_references}"
        )
    if request.enabled_channels is not None:
        request.lines.append(f"enabled_channels: {sorted(request.enabled_channels)}")
    if request.channel_priority is not None:
        request.lines.append(f"channel_priority: {request.channel_priority}")
    if request.ordered_channels is not None:
        request.lines.append(f"ordered_channels: {request.ordered_channels}")
    if request.producers is not None:
        request.lines.append("retrieval_producers:")
        for producer in request.producers:
            request.lines.append(
                "  "
                f"{producer['producer_name']}"
                f" v{producer['producer_version']}"
                f" capability_version={producer['capability_version']}"
                f" source={producer['source_kind']}:{producer['source_name']}"
            )
            request.lines.append(
                f"    known_capabilities={producer['known_capabilities']}"
            )
            request.lines.append(
                f"    unknown_capabilities={producer['unknown_capabilities']}"
            )
    if request.signal_collection is not None:
        request.lines.append(
            f"signal_collection: total_signals={request.signal_collection['total_signals']}"
        )
        request.lines.append(f"  families={request.signal_collection['families']}")
        request.lines.append(
            f"  capabilities={request.signal_collection['capabilities']}"
        )
        request.lines.append(
            f"  used_producers={request.signal_collection['used_producers']}"
        )
        request.lines.append(
            f"  ignored_producers={request.signal_collection['ignored_producers']}"
        )
    request.lines.append("")


def _append_explain_signal_sections(
    request: ExplainSectionsRequest,
) -> None:
    """
    Append explain sections for signals, channel results, and signal merge.

    Parameters
    ----------
    request : ExplainSectionsRequest
        Explain-section render request.

    Returns
    -------
    None
        Signal-oriented explain sections are appended in place.
    """
    if request.signal_preview is not None:
        request.lines.append("=== EXPLAIN: SIGNALS ===")
        for entry in request.signal_preview:
            _append_explain_signal_preview_entry(request.lines, entry)
        request.lines.append("")

    if request.bundles is not None:
        request.lines.append("=== EXPLAIN: CHANNEL RESULTS ===")
        for channel_name, channel in sorted(request.bundles, key=lambda item: item[0]):
            request.lines.append(f"{channel_name}:")
            if not channel:
                request.lines.append("  (no results)")
                continue
            for score, symbol in channel[:5]:
                symbol_type, module_name, name, _file_path, lineno = symbol
                label = (
                    f"{module_name}:{lineno}"
                    if symbol_type == "module"
                    else f"{module_name}.{name}:{lineno}"
                )
                request.lines.append(f"  {score:.2f} -> {label}")
        request.lines.append("")

    if request.signal_merge is not None:
        request.lines.append("=== EXPLAIN: SIGNAL MERGE ===")
        for entry in request.signal_merge:
            _append_explain_signal_merge_entry(request.lines, entry)
        request.lines.append("")


def _append_explain_signal_preview_entry(
    lines: list[str],
    entry: dict[str, object],
) -> None:
    """
    Append one explain preview entry for a normalized retrieval signal.

    Parameters
    ----------
    lines : list[str]
        Mutable explain output buffer.
    entry : dict[str, object]
        One compact signal preview entry.

    Returns
    -------
    None
        The preview lines are appended to ``lines`` in place.
    """
    label = f"{entry['kind']} {entry['module']}.{entry['name']}:{entry['lineno']}"
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
    if "evidence_detail" in entry:
        lines.append(f"    evidence={entry['evidence_detail']}")
    if "distance" in entry:
        lines.append(f"    distance={entry['distance']}")
    if "source" in entry:
        source = cast("dict[str, object]", entry["source"])
        lines.append(
            f"    source={source['module']}.{source['name']}:{source['lineno']}"
        )


def _append_explain_signal_merge_entry(
    lines: list[str],
    entry: dict[str, object],
) -> None:
    """
    Append one explain merge summary entry for a ranked symbol.

    Parameters
    ----------
    lines : list[str]
        Mutable explain output buffer.
    entry : dict[str, object]
        One compact per-symbol signal summary entry.

    Returns
    -------
    None
        The merge-summary lines are appended to ``lines`` in place.
    """
    lines.append(
        "  "
        f"{entry['module']}.{entry['name']}:{entry['lineno']}"
        f" signal_count={entry['signal_count']}"
    )
    lines.append(f"    families={entry['families']}")
    lines.append(f"    capabilities={entry['capabilities']}")
    if "evidence" in entry:
        lines.append(f"    evidence={entry['evidence']}")
    lines.append(f"    producers={entry['producers']}")


def _append_explain_merge_sections(
    request: ExplainSectionsRequest,
) -> None:
    """
    Append explain sections for merge and diversity diagnostics.

    Parameters
    ----------
    request : ExplainSectionsRequest
        Explain-section render request.

    Returns
    -------
    None
        Merge-oriented explain sections are appended in place.
    """
    if request.provenance is not None:
        request.lines.append("=== EXPLAIN: MERGE ===")
        for symbol in request.top_matches:
            symbol_type, module_name, name, _file_path, lineno = symbol
            label = (
                f"{module_name}:{lineno}"
                if symbol_type == "module"
                else f"{module_name}.{name}:{lineno}"
            )
            merge_details = request.provenance.get(symbol)
            if not merge_details:
                continue
            request.lines.append(label)
            role = _classify_file_role(symbol[3], module_name)
            role_bias = _file_role_bias(role, request.intent)
            request.lines.append(
                "  "
                f"winner={cast('str', merge_details['winner'])} "
                f"rrf_score={cast('float', merge_details['rrf_score']):.4f} "
                f"evidence_bonus={cast('float', merge_details['evidence_bonus']):.4f} "
                f"role_bonus={cast('float', merge_details['role_bonus']):.4f} "
                f"merge_score={cast('float', merge_details['merge_score']):.4f}"
            )
            request.lines.append(f"  role={role} role_bias={role_bias}")
            for family_name, score in cast(
                "dict[str, float]",
                merge_details["families"],
            ).items():
                request.lines.append(f"  family.{family_name}: {score:.2f}")
            for channel_name, score in cast(
                "dict[str, float]",
                merge_details["channels"],
            ).items():
                request.lines.append(f"  channel.{channel_name}: {score:.2f}")
        request.lines.append("")

    if request.diversity is not None:
        request.lines.append("=== EXPLAIN: DIVERSITY ===")
        request.lines.append(f"max_per_file: {MERGE_MAX_PER_FILE}")
        request.lines.append(f"role_caps: {MERGE_ROLE_CAPS}")
        request.lines.append(f"language_caps: {MERGE_LANGUAGE_CAPS}")

        selected_entries = request.diversity.get("selected")
        if isinstance(selected_entries, list) and selected_entries:
            request.lines.append("selected:")
            for entry in selected_entries[: len(request.top_matches)]:
                label = (
                    f"{entry.get('module')}.{entry.get('name')}:{entry.get('lineno')}"
                )
                request.lines.append(
                    "  "
                    f"{label} role={entry.get('role')} "
                    f"language={entry.get('language')} "
                    f"stage={entry.get('selection_stage')}"
                )

        deferred_entries = request.diversity.get("deferred")
        if isinstance(deferred_entries, list) and deferred_entries:
            request.lines.append("deferred:")
            for entry in deferred_entries[:5]:
                label = (
                    f"{entry.get('module')}.{entry.get('name')}:{entry.get('lineno')}"
                )
                request.lines.append(
                    "  "
                    f"{label} role={entry.get('role')} "
                    f"language={entry.get('language')} "
                    f"reason={entry.get('reason')}"
                )
        request.lines.append("")


def _append_explain_expansion_section(
    request: ExplainSectionsRequest,
) -> None:
    """
    Append the explain section for graph-expansion diagnostics.

    Parameters
    ----------
    request : ExplainSectionsRequest
        Explain-section render request.

    Returns
    -------
    None
        Expansion diagnostics are appended in place when present.
    """
    if request.expansion is None:
        return
    budget_entries = request.expansion.get("graph_budget")
    include_entries = request.expansion.get("include_graph")
    has_budget_entries = isinstance(budget_entries, list) and bool(budget_entries)
    has_include_entries = isinstance(include_entries, list) and bool(include_entries)
    if not (has_budget_entries or has_include_entries):
        return
    request.lines.append("=== EXPLAIN: EXPANSION ===")
    if has_budget_entries:
        budget_entries = cast("list[dict[str, object]]", budget_entries)
        request.lines.append("graph_budget:")
        for entry in budget_entries[:10]:
            request.lines.append(
                "  "
                f"rank={entry.get('top_match_rank')} "
                f"symbol={entry.get('module')}.{entry.get('name')} "
                f"include={entry.get('include_graph_reason')} "
                f"relations={entry.get('relation_reason')}"
            )
    if has_include_entries:
        include_entries = cast("list[dict[str, object]]", include_entries)
        request.lines.append("include_graph:")
        for entry in include_entries[:10]:
            request.lines.append(
                "  "
                f"seed={entry.get('seed_module')} "
                f"via={entry.get('via_module')} "
                f"target={entry.get('target_name')} "
                f"direction={entry.get('direction')} "
                f"expanded={entry.get('expanded_module')}.{entry.get('expanded_name')}"
            )
    request.lines.append("")


def _append_explain_sections(
    request: ExplainSectionsRequest,
) -> None:
    """
    Append explain-mode sections to the plain-text output buffer.

    Parameters
    ----------
    request : ExplainSectionsRequest
        Explain-section render request.

    Returns
    -------
    None
        The explain sections are appended to ``request.lines`` in place.

    Notes
    -----
    Rendering is gated by ``request.explain``. When explain mode is disabled,
    the function leaves ``request.lines`` unchanged.
    """
    if not request.explain:
        return
    _append_explain_environment(request)
    _append_explain_signal_sections(request)
    _append_explain_merge_sections(request)
    _append_explain_expansion_section(request)


def _append_top_matches_section(request: MainContextSectionsRequest) -> None:
    """
    Append the top-match section to the plain-text context output.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        Top matches are appended to ``request.lines`` in place.
    """
    request.lines.append("=== TOP MATCHES ===")
    if not request.top_matches:
        request.lines.append("No direct symbol matches found.")
        return
    for symbol in request.top_matches:
        request.lines.append(_format_symbol(request.root, symbol, include_path=True))


def _normalized_doc_issue_message(message: str) -> str:
    """
    Normalize one doc-issue message for plain-text display.

    Parameters
    ----------
    message : str
        Raw stored doc-issue message.

    Returns
    -------
    str
        User-facing doc-issue message.
    """
    if message.startswith("Module ") and message.endswith("Missing docstring"):
        return message.replace(
            "Missing docstring",
            "Missing module-level docstring",
        )
    return message


def _append_doc_issues_section(request: MainContextSectionsRequest) -> None:
    """
    Append the related-docstring-issues section to the context output.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        Docstring issues are appended to ``request.lines`` in place.
    """
    request.lines.append("\n=== RELATED DOCSTRING ISSUES ===")
    if not request.doc_issues:
        request.lines.append("No related docstring issues.")
        return
    for issue_type, message in request.doc_issues:
        request.lines.append(f"{issue_type}: {_normalized_doc_issue_message(message)}")


def _append_suggested_context_section(request: MainContextSectionsRequest) -> None:
    """
    Append enriched symbol context blocks to the plain-text output.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        Enriched context is appended to ``request.lines`` in place.
    """
    request.lines.append("\n=== SUGGESTED CONTEXT ===")
    cache: dict[Path, tuple[str, list[str]]] = {}
    for index, symbol in enumerate(request.top_matches[:ENRICHED_CONTEXT_LIMIT]):
        if index > 0:
            request.lines.append("")
        request.lines.extend(
            _format_enriched_symbol(
                request.root,
                symbol,
                cache,
                max_source_file_bytes=request.max_source_file_bytes,
            )
        )


def _append_module_expansion_section(request: MainContextSectionsRequest) -> None:
    """
    Append the module-expansion section to the plain-text context output.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        Module-expansion entries are appended to ``request.lines`` in place.
    """
    request.lines.append("\n=== MODULE EXPANSION ===")
    if not request.expanded:
        request.lines.append("No module expansion available.")
        return
    for symbol in request.expanded:
        request.lines.append(_format_symbol(request.root, symbol, include_path=False))


def _relative_reference_text(root: Path, file_path: str) -> str:
    """
    Convert one absolute reference path into a repo-relative display path.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to relativize paths.
    file_path : str
        Absolute or external file path recorded in one reference row.

    Returns
    -------
    str
        Relative path when the file lives under ``root``, otherwise the
        original path text.
    """
    try:
        return str(Path(file_path).relative_to(root))
    except ValueError:
        return str(file_path)


def _append_cross_module_references_section(
    request: MainContextSectionsRequest,
) -> None:
    """
    Append the cross-module-reference section to the context output.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        Cross-module references are appended to ``request.lines`` in place.
    """
    request.lines.append("\n=== CROSS-MODULE REFERENCES ===")
    if not request.unique_refs:
        request.lines.append("No cross-module references found.")
        return
    for file_path, lineno in request.unique_refs:
        request.lines.append(
            f"{_relative_reference_text(request.root, file_path)}:{lineno}"
        )


def _append_main_context_sections(
    request: MainContextSectionsRequest,
) -> None:
    """
    Append the main plain-text context sections to the output buffer.

    Parameters
    ----------
    request : MainContextSectionsRequest
        Main plain-text section render request.

    Returns
    -------
    None
        The main context sections are appended to ``request.lines`` in place.

    Notes
    -----
    The function preserves the ranked order of ``request.top_matches`` and only emits
    enriched blocks for the configured leading subset.
    """
    _append_top_matches_section(request)
    _append_doc_issues_section(request)
    _append_suggested_context_section(request)
    _append_module_expansion_section(request)
    _append_cross_module_references_section(request)
