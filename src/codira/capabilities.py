"""Machine-readable capability contract export for codira.

Responsibilities
----------------
- Define the Layer 0 capability contract exported by ``codira capabilities``.
- Validate analyzer declarations against the canonical ontology.
- Assemble command, channel, analyzer, and retrieval-producer metadata without
  changing indexing or query behavior.

Design principles
-----------------
The capability export is explicit and deterministic. Missing analyzer
declarations are reported as contract failures instead of being inferred from
runtime behavior.

Architectural role
------------------
This module belongs to the **capability contract layer** described by issue #7.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from codira.contracts import (
    CANONICAL_ONTOLOGY_TYPES,
    KNOWN_RETRIEVAL_CAPABILITIES,
    AnalyzerCapabilityDeclaration,
    CapabilityDeclaringAnalyzer,
    LanguageAnalyzer,
    split_declared_retrieval_capabilities,
)
from codira.query.producers import (
    CHANNEL_PRODUCER_SPECS,
    ENRICHMENT_PRODUCER_SPECS,
    QueryProducerSpec,
)
from codira.registry import active_language_analyzers

if TYPE_CHECKING:
    from collections.abc import Sequence

CAPABILITY_SCHEMA_VERSION = "1.0"
ONTOLOGY_VERSION = "1"

COMMAND_CONTRACTS: dict[str, dict[str, object]] = {
    "index": {
        "intent": "build_or_refresh_index",
        "channels": [],
        "guarantee": "deterministic_backend_index_update",
        "limitations": [
            "coverage depends on active analyzers",
            "semantic embeddings depend on the configured embedding backend",
        ],
    },
    "cov": {
        "intent": "coverage_audit",
        "channels": [],
        "guarantee": "deterministic_analyzer_coverage_report",
        "limitations": ["coverage roots are currently repository-policy defined"],
    },
    "sym": {
        "intent": "exact_symbol_lookup",
        "channels": ["symbol"],
        "guarantee": "exact_name_match_only",
        "limitations": [
            "matches only persisted symbols",
            "no partial or fuzzy matching",
            "coverage depends on analyzer declarations and parser support",
        ],
    },
    "emb": {
        "intent": "embedding_similarity_lookup",
        "channels": ["embedding"],
        "guarantee": "embedding_backend_similarity_order",
        "limitations": [
            "approximate natural-language relevance",
            "requires persisted embeddings for indexed artifacts",
        ],
    },
    "calls": {
        "intent": "static_call_graph_lookup",
        "channels": ["call_graph"],
        "guarantee": "deterministic_static_graph_edges",
        "limitations": ["call resolution is conservative and analyzer-limited"],
    },
    "refs": {
        "intent": "callable_reference_lookup",
        "channels": ["references"],
        "guarantee": "deterministic_static_reference_edges",
        "limitations": ["reference resolution is conservative and analyzer-limited"],
    },
    "audit": {
        "intent": "docstring_issue_lookup",
        "channels": ["doc_issues"],
        "guarantee": "deterministic_docstring_issue_rows",
        "limitations": ["audit policy is convention-specific"],
    },
    "ctx": {
        "intent": "task_focused_context_retrieval",
        "channels": ["symbol", "semantic", "embedding"],
        "guarantee": "deterministic_channel_merge_for_current_index",
        "limitations": [
            "ranking depends on declared producer capabilities",
            "semantic and embedding channels are supporting evidence",
        ],
    },
    "plugins": {
        "intent": "plugin_registration_diagnostics",
        "channels": [],
        "guarantee": "deterministic_plugin_snapshot",
        "limitations": ["entry-point discovery depends on installed distributions"],
    },
    "capabilities": {
        "intent": "capability_contract_export",
        "channels": [],
        "guarantee": "deterministic_layer_0_contract_export",
        "limitations": ["fails when active analyzers do not declare capabilities"],
    },
}


def _ontology_payload() -> dict[str, object]:
    """
    Build the canonical ontology payload.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Versioned ontology metadata.
    """
    return {
        "version": ONTOLOGY_VERSION,
        "types": list(CANONICAL_ONTOLOGY_TYPES),
    }


def _producer_payload(spec: QueryProducerSpec) -> dict[str, object]:
    """
    Convert one query producer spec to JSON-compatible metadata.

    Parameters
    ----------
    spec : codira.query.producers.QueryProducerSpec
        Query producer specification carrying capability metadata.

    Returns
    -------
    dict[str, object]
        Producer metadata with known and unknown capability partitions.
    """
    producer_name = spec.producer_name
    producer_version = spec.producer_version
    capability_version = spec.capability_version
    capabilities = tuple(str(value) for value in spec.capabilities)
    known, unknown = split_declared_retrieval_capabilities(capabilities)
    return {
        "producer_name": producer_name,
        "producer_version": producer_version,
        "capability_version": capability_version,
        "source_kind": spec.source_kind,
        "source_name": spec.source_name,
        "declared_capabilities": list(capabilities),
        "known_capabilities": list(known),
        "unknown_capabilities": list(unknown),
    }


def _retrieval_producer_payloads() -> list[dict[str, object]]:
    """
    Return deterministic retrieval producer declarations.

    Parameters
    ----------
    None

    Returns
    -------
    list[dict[str, object]]
        Channel and enrichment producer metadata.
    """
    specs = [
        *[CHANNEL_PRODUCER_SPECS[name] for name in sorted(CHANNEL_PRODUCER_SPECS)],
        *[
            ENRICHMENT_PRODUCER_SPECS[name]
            for name in sorted(ENRICHMENT_PRODUCER_SPECS)
        ],
    ]
    return [_producer_payload(spec) for spec in specs]


def _validate_declaration(
    declaration: AnalyzerCapabilityDeclaration,
) -> list[str]:
    """
    Validate one analyzer declaration against the canonical ontology.

    Parameters
    ----------
    declaration : AnalyzerCapabilityDeclaration
        Analyzer declaration to validate.

    Returns
    -------
    list[str]
        Deterministic validation messages. An empty list means the declaration
        is valid.
    """
    issues: list[str] = []
    ontology = set(CANONICAL_ONTOLOGY_TYPES)
    supports = set(declaration.supports)
    does_not_support = set(declaration.does_not_support)

    if not declaration.analyzer_name.strip():
        issues.append("analyzer name is empty")
    if not declaration.analyzer_version.strip():
        issues.append(f"{declaration.analyzer_name}: analyzer version is empty")
    if not declaration.entrypoint.strip():
        issues.append(f"{declaration.analyzer_name}: entrypoint is empty")
    if not declaration.mappings:
        issues.append(f"{declaration.analyzer_name}: mappings are empty")

    unknown_supported = sorted(supports - ontology)
    if unknown_supported:
        issues.append(
            f"{declaration.analyzer_name}: unsupported ontology types in supports: "
            + ", ".join(unknown_supported)
        )

    unknown_negative = sorted(does_not_support - ontology)
    if unknown_negative:
        issues.append(
            f"{declaration.analyzer_name}: unsupported ontology types in "
            "does_not_support: " + ", ".join(unknown_negative)
        )

    overlap = sorted(supports & does_not_support)
    if overlap:
        issues.append(
            f"{declaration.analyzer_name}: ontology types declared as both "
            "supported and unsupported: " + ", ".join(overlap)
        )

    omitted = sorted(ontology - supports - does_not_support)
    if omitted:
        issues.append(
            f"{declaration.analyzer_name}: ontology types omitted from declaration: "
            + ", ".join(omitted)
        )

    invalid_mapping_targets = sorted(
        {
            target
            for target in declaration.mappings.values()
            if target not in CANONICAL_ONTOLOGY_TYPES
        }
    )
    if invalid_mapping_targets:
        issues.append(
            f"{declaration.analyzer_name}: mappings target unknown ontology types: "
            + ", ".join(invalid_mapping_targets)
        )

    return issues


def _declaration_payload(
    declaration: AnalyzerCapabilityDeclaration,
) -> dict[str, object]:
    """
    Convert an analyzer declaration to deterministic JSON-compatible data.

    Parameters
    ----------
    declaration : AnalyzerCapabilityDeclaration
        Analyzer declaration to serialize.

    Returns
    -------
    dict[str, object]
        JSON-compatible analyzer declaration payload.
    """
    payload = asdict(declaration)
    payload["supports"] = list(declaration.supports)
    payload["does_not_support"] = list(declaration.does_not_support)
    payload["mappings"] = dict(sorted(declaration.mappings.items()))
    return payload


def _analyzer_declarations(
    analyzers: Sequence[LanguageAnalyzer],
) -> tuple[list[dict[str, object]], list[str]]:
    """
    Collect and validate active analyzer capability declarations.

    Parameters
    ----------
    analyzers : collections.abc.Sequence[LanguageAnalyzer]
        Active analyzers to inspect.

    Returns
    -------
    tuple[list[dict[str, object]], list[str]]
        Serialized declarations and validation issues.
    """
    declarations: list[AnalyzerCapabilityDeclaration] = []
    issues: list[str] = []

    for analyzer in sorted(analyzers, key=lambda item: str(item.name)):
        if not isinstance(analyzer, CapabilityDeclaringAnalyzer):
            issues.append(f"{analyzer.name}: analyzer does not declare capabilities")
            continue
        declaration = analyzer.analyzer_capability_declaration()
        if declaration.analyzer_name != analyzer.name:
            issues.append(
                f"{analyzer.name}: declaration name {declaration.analyzer_name!r} "
                "does not match analyzer name"
            )
        if declaration.analyzer_version != analyzer.version:
            issues.append(
                f"{analyzer.name}: declaration version "
                f"{declaration.analyzer_version!r} does not match analyzer version"
            )
        issues.extend(_validate_declaration(declaration))
        declarations.append(declaration)

    payloads = [_declaration_payload(declaration) for declaration in declarations]
    return payloads, sorted(issues)


def build_capability_contract(
    analyzers: Sequence[LanguageAnalyzer] | None = None,
) -> dict[str, object]:
    """
    Build the deterministic Layer 0 capability contract.

    Parameters
    ----------
    analyzers : collections.abc.Sequence[LanguageAnalyzer] | None, optional
        Analyzer instances to describe. When omitted, active analyzers are
        loaded through the registry.

    Returns
    -------
    dict[str, object]
        JSON-compatible capability contract payload.

    Raises
    ------
    ValueError
        If active analyzers are missing valid capability declarations.
    """
    active_analyzers = active_language_analyzers() if analyzers is None else analyzers
    analyzer_payloads, validation_issues = _analyzer_declarations(active_analyzers)
    if validation_issues:
        joined = "; ".join(validation_issues)
        msg = f"Invalid capability declarations: {joined}"
        raise ValueError(msg)

    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "ontology": _ontology_payload(),
        "commands": dict(sorted(COMMAND_CONTRACTS.items())),
        "channels": {
            "call_graph": {
                "match": "static_graph",
                "source": "call_edges",
                "guarantee": "deterministic_static_call_edges",
            },
            "doc_issues": {
                "match": "diagnostic",
                "source": "docstring_issues",
                "guarantee": "deterministic_issue_annotations",
            },
            "embedding": {
                "match": "approximate",
                "source": "embeddings",
                "guarantee": "embedding_backend_similarity_order",
            },
            "references": {
                "match": "static_graph",
                "source": "callable_refs",
                "guarantee": "deterministic_static_reference_edges",
            },
            "semantic": {
                "match": "heuristic_text",
                "source": "symbol_text",
                "guarantee": "deterministic_lexical_semantic_scoring",
            },
            "symbol": {
                "match": "exact",
                "source": "symbol_index",
                "guarantee": "exact_name_match_only",
            },
        },
        "retrieval_capabilities": list(KNOWN_RETRIEVAL_CAPABILITIES),
        "retrieval_producers": _retrieval_producer_payloads(),
        "analyzers": analyzer_payloads,
        "validation": {
            "status": "ok",
            "issues": [],
        },
    }
