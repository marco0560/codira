"""Deterministic query-intent classification for retrieval routing.

Responsibilities
----------------
- Provide structured models (`QueryIntent`, `RetrievalPlan`) capturing query intent, channel choices, and enrichment flags.
- Classify raw queries into intent families such as behavior, test, configuration, API surface, and architecture.
- Expose helper functions that inform retrieval plans used by the context builder.

Design principles
-----------------
Classification logic is deterministic, repository-agnostic, and relies only on textual cues to avoid implicit domain assumptions.

Architectural role
------------------
This module belongs to the **query planning layer** that routes retrieval work before context assembly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from codira.types import ChannelName

IntentFamily = Literal[
    "behavior",
    "test",
    "configuration",
    "api_surface",
    "architecture",
]


@dataclass(frozen=True)
class QueryIntent:
    """
    Structured classification of a query.

    Parameters
    ----------
    raw : str
        Original query string.
    is_identifier_query : bool
        Whether the query looks like a single identifier or symbol lookup.
    is_multi_term : bool
        Whether the query contains multiple whitespace-separated terms.
    is_test_related : bool
        Whether the query explicitly targets tests.
    is_script_related : bool
        Whether the query explicitly targets scripts.
    primary_intent : {
        "behavior", "test", "configuration", "api_surface", "architecture"
    }
        Deterministic primary intent family used by the retrieval planner.

    Returns
    -------
    None
        Dataclasses do not return a value from initialization.

    Notes
    -----
    This model is intentionally structural and repository-agnostic.
    """

    raw: str
    is_identifier_query: bool
    is_multi_term: bool
    is_test_related: bool
    is_script_related: bool
    primary_intent: IntentFamily


@dataclass(frozen=True)
class RetrievalPlan:
    """
    Deterministic retrieval plan derived from classified query intent.

    Parameters
    ----------
    primary_intent : {
        "behavior", "test", "configuration", "api_surface", "architecture"
    }
        Primary planner category used to route retrieval.
    channels : tuple[str, ...]
        Enabled retrieval channels in priority order.
    include_doc_issues : bool
        Whether docstring issue enrichment should run.
    include_include_graph : bool
        Whether C include-graph expansion should run.
    include_references : bool
        Whether cross-module reference collection should run.
    """

    primary_intent: IntentFamily
    channels: tuple[ChannelName, ...]
    include_doc_issues: bool
    include_include_graph: bool
    include_references: bool


def _primary_intent(
    query: str,
    *,
    is_identifier_query: bool,
    is_test_related: bool,
    is_script_related: bool,
) -> IntentFamily:
    """
    Resolve the primary intent family for a query.

    Parameters
    ----------
    query : str
        Raw lowercased query string.
    is_identifier_query : bool
        Whether the query looks like a direct identifier lookup.
    is_test_related : bool
        Whether the query explicitly targets tests.
    is_script_related : bool
        Whether the query explicitly targets scripts or command paths.

    Returns
    -------
    IntentFamily
        Deterministic primary intent family.
    """
    if is_test_related:
        return "test"

    if any(
        kw in query
        for kw in (
            "config",
            "configuration",
            "settings",
            "option",
            "options",
            "flag",
            "flags",
            "env",
            "environment",
            "variable",
            "variables",
        )
    ):
        return "configuration"

    if is_script_related:
        return "configuration"

    if any(
        kw in query
        for kw in (
            "architecture",
            "design",
            "overview",
            "flow",
            "pipeline",
            "graph",
            "relationship",
            "relationships",
            "where",
            "navigation",
            "navigate",
            "layout",
            "structure",
        )
    ):
        return "architecture"

    if is_identifier_query or any(
        kw in query
        for kw in (
            "api",
            "interface",
            "signature",
            "signatures",
            "public",
            "method",
            "methods",
            "function",
            "functions",
            "class",
            "classes",
            "symbol",
            "symbols",
        )
    ):
        return "api_surface"

    return "behavior"


def classify_query(query: str) -> QueryIntent:
    """
    Classify a query into structural intent categories.

    Parameters
    ----------
    query : str
        Raw user query string.

    Returns
    -------
    QueryIntent
        Structured intent flags describing the shape of the query.

    Notes
    -----
    Classification is deterministic and repository-agnostic. It avoids
    domain-specific keywords and relies only on query structure.
    """
    q = query.strip()
    tokens = [t for t in q.split() if t]

    is_identifier_query = bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", q))
    is_multi_term = len(tokens) >= 2

    lowered = q.lower()

    is_test_related = any(kw in lowered for kw in ("test", "tests", "pytest"))

    is_script_related = any(
        kw in lowered for kw in ("script", "scripts", "cli", "command")
    )
    primary_intent = _primary_intent(
        lowered,
        is_identifier_query=is_identifier_query,
        is_test_related=is_test_related,
        is_script_related=is_script_related,
    )

    return QueryIntent(
        raw=q,
        is_identifier_query=is_identifier_query,
        is_multi_term=is_multi_term,
        is_test_related=is_test_related,
        is_script_related=is_script_related,
        primary_intent=primary_intent,
    )


def build_retrieval_plan(intent: QueryIntent) -> RetrievalPlan:
    """
    Build the deterministic retrieval plan for a classified query.

    Parameters
    ----------
    intent : QueryIntent
        Structured query classification.

    Returns
    -------
    RetrievalPlan
        Planner directives for channel routing and follow-on enrichment.
    """
    if intent.primary_intent == "test":
        return RetrievalPlan(
            primary_intent="test",
            channels=("test", "symbol", "embedding", "semantic"),
            include_doc_issues=False,
            include_include_graph=False,
            include_references=True,
        )
    if intent.primary_intent == "configuration":
        return RetrievalPlan(
            primary_intent="configuration",
            channels=("script", "symbol", "embedding", "semantic"),
            include_doc_issues=False,
            include_include_graph=False,
            include_references=True,
        )
    if intent.primary_intent == "api_surface":
        return RetrievalPlan(
            primary_intent="api_surface",
            channels=("symbol", "embedding", "semantic"),
            include_doc_issues=True,
            include_include_graph=True,
            include_references=True,
        )
    if intent.primary_intent == "architecture":
        return RetrievalPlan(
            primary_intent="architecture",
            channels=("symbol", "semantic", "embedding"),
            include_doc_issues=False,
            include_include_graph=True,
            include_references=True,
        )
    return RetrievalPlan(
        primary_intent="behavior",
        channels=("symbol", "embedding", "semantic"),
        include_doc_issues=True,
        include_include_graph=True,
        include_references=True,
    )
