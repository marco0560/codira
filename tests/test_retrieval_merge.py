"""Regression tests for retrieval merge stability.

Responsibilities
----------------
- Assert channel deduplication, tie-breaking, and cross-family bonuses in merge helpers.
- Validate final merged ordering, provenance metrics, and role/explain data.

Design principles
-----------------
Tests keep merge coverage specific to fix retrieval ordering so merged outputs stay deterministic.

Architectural role
------------------
This module belongs to the **retrieval verification layer** that ensures stable merged outputs for prompts and CLI consumers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.query.classifier import build_retrieval_plan, classify_query
from codira.query.context import (
    MERGE_RESULT_LIMIT,
    _bounded_graph_retrieval_signals,
    _channel_retrieval_producers,
    _collect_retrieval_signals,
    _dedupe_channel_results,
    _diversify_merged_symbols,
    _diversify_merged_symbols_explain,
    _merge_ranked_channel_bundles_explain,
    _rank_signals_with_provenance,
    _signals_from_channel_bundles,
)
from codira.query.producers import (
    CALL_GRAPH_RETRIEVAL_PRODUCER,
    CHANNEL_PRODUCER_SPECS,
    EMBEDDING_RETRIEVAL_PRODUCER,
    INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    REFERENCE_RETRIEVAL_PRODUCER,
    selected_enrichment_producers,
)

if TYPE_CHECKING:
    from codira.query.producers import QueryProducerSpec
    from codira.types import ChannelResults, SymbolRow


def _symbol(
    symbol_type: str,
    module_name: str,
    name: str,
    file_path: str,
    lineno: int,
) -> SymbolRow:
    """
    Create one compact symbol row for retrieval-merge fixtures.

    Parameters
    ----------
    symbol_type : str
        Symbol kind stored in the row.
    module_name : str
        Dotted module name owning the symbol.
    name : str
        Symbol name.
    file_path : str
        Repository-relative source path for the symbol.
    lineno : int
        Defining line number for the symbol.

    Returns
    -------
    codira.types.SymbolRow
        Compact symbol row used in merge tests.
    """
    return (symbol_type, module_name, name, file_path, lineno)


def _query_producers(
    query: str, bundles: list[tuple[str, ChannelResults]]
) -> list[QueryProducerSpec]:
    """
    Compose query producer specs for retrieval-merge fixtures.

    Parameters
    ----------
    query : str
        Query text used to derive the retrieval plan.
    bundles : list[tuple[str, ChannelResults]]
        Ranked channel bundles included in the fixture.

    Returns
    -------
    list[QueryProducerSpec]
        Query producer specifications matching the fixture channels and
        enabled enrichments.
    """
    plan = build_retrieval_plan(classify_query(query))
    ordered_channels = [name for name, _channel in bundles]
    return _channel_retrieval_producers(
        ordered_channels
    ) + selected_enrichment_producers(
        include_issue_annotations="issue" in query.lower() or plan.include_doc_issues,
        include_references=plan.include_references,
        include_include_graph=plan.include_include_graph,
    )


def test_dedupe_channel_results_keeps_first_ranked_occurrence() -> None:
    """
    Ensure channel-local deduplication preserves the best-ranked occurrence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that duplicate channel entries keep the first rank.
    """
    symbol = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    other = _symbol("function", "codira.beta", "run", "src/b.py", 20)
    channel: ChannelResults = [
        (9.0, symbol),
        (8.0, symbol),
        (7.0, other),
    ]

    deduped = _dedupe_channel_results(channel)

    assert deduped == [
        (9.0, symbol),
        (7.0, other),
    ]


def test_embedding_channel_uses_native_retrieval_producer() -> None:
    """
    Keep the embedding channel bound to the native retrieval producer.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the shared producer surface exposes the native
        embedding producer instance directly.
    """
    assert CHANNEL_PRODUCER_SPECS["embedding"] is EMBEDDING_RETRIEVAL_PRODUCER


def test_graph_enrichment_specs_use_native_retrieval_producers() -> None:
    """
    Keep graph enrichment metadata bound to native producer instances.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts selected enrichment producers preserve their
        deterministic order while exposing native call, reference, and include
        producer instances.
    """
    producers = selected_enrichment_producers(
        include_issue_annotations=False,
        include_references=True,
        include_include_graph=True,
    )

    assert producers == [
        CALL_GRAPH_RETRIEVAL_PRODUCER,
        REFERENCE_RETRIEVAL_PRODUCER,
        INCLUDE_GRAPH_RETRIEVAL_PRODUCER,
    ]


def test_merge_ranked_channel_bundles_explain_dedupes_and_orders_ties() -> None:
    """
    Ensure merged output is unique and tie ordering is deterministic.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts deterministic tie ordering and provenance.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "codira.beta", "run", "src/b.py", 20)

    bundles = [
        (
            "semantic",
            [
                (5.0, beta),
                (4.0, beta),
            ],
        ),
        (
            "symbol",
            [
                (9.0, alpha),
                (8.0, alpha),
            ],
        ),
    ]

    merged, provenance = _merge_ranked_channel_bundles_explain(bundles)

    assert merged == [alpha, beta]
    assert provenance[alpha] == {
        "channels": {"symbol": 9.0},
        "families": {"lexical": 9.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.0,
        "role_bonus": 0.75,
        "merge_score": 1.75,
        "winner": "symbol",
    }
    assert provenance[beta] == {
        "channels": {"semantic": 5.0},
        "families": {"semantic": 5.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.0,
        "role_bonus": 0.75,
        "merge_score": 1.75,
        "winner": "semantic",
    }


def test_merge_ranked_channel_bundles_explain_rewards_cross_family_support() -> None:
    """
    Prefer symbols supported by more than one evidence family.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the merge layer applies a deterministic bonus when a
        symbol is corroborated by both lexical and semantic evidence.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "codira.beta", "run", "src/b.py", 20)
    gamma = _symbol("function", "codira.gamma", "run", "src/c.py", 30)

    bundles = [
        (
            "symbol",
            [
                (9.0, alpha),
                (8.0, beta),
            ],
        ),
        (
            "semantic",
            [
                (5.0, gamma),
                (4.0, beta),
            ],
        ),
    ]

    merged, provenance = _merge_ranked_channel_bundles_explain(bundles)

    assert merged[:2] == [beta, alpha]
    assert provenance[beta] == {
        "channels": {"symbol": 8.0, "semantic": 4.0},
        "families": {"lexical": 8.0, "semantic": 4.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.15,
        "role_bonus": 0.75,
        "merge_score": 1.9,
        "winner": "symbol",
    }


def test_merge_ranked_channel_bundles_explain_applies_role_bonus() -> None:
    """
    Expose merge-time role contribution separately from family evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts implementation symbols gain a visible merge bonus
        over tests for default non-test queries.
    """
    implementation = _symbol("function", "pkg.core", "cache_flow", "src/core.py", 10)
    test_symbol = _symbol(
        "function",
        "tests.test_core",
        "cache_flow_test",
        "tests/test_core.py",
        20,
    )
    bundles = [
        (
            "semantic",
            [
                (5.0, test_symbol),
                (4.0, implementation),
            ],
        )
    ]

    merged, provenance = _merge_ranked_channel_bundles_explain(
        bundles,
        intent=classify_query("cache invalidation"),
    )

    assert merged[:2] == [implementation, test_symbol]
    assert provenance[implementation] == {
        "channels": {"semantic": 4.0},
        "families": {"semantic": 4.0},
        "rrf_score": 0.5,
        "evidence_bonus": 0.0,
        "role_bonus": 0.75,
        "merge_score": 1.25,
        "winner": "semantic",
    }
    assert provenance[test_symbol] == {
        "channels": {"semantic": 5.0},
        "families": {"semantic": 5.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.0,
        "role_bonus": -1.0,
        "merge_score": 0.0,
        "winner": "semantic",
    }


def test_merge_ranked_channel_bundles_explain_caps_output() -> None:
    """
    Ensure merged output is capped by the module-level limit.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts enforcement of the merged-output cap.
    """
    bundles = [
        (
            "symbol",
            [
                (
                    float(MERGE_RESULT_LIMIT - idx),
                    _symbol(
                        "function",
                        f"codira.module_{idx:02d}",
                        "run",
                        f"src/module_{idx:02d}.py",
                        idx,
                    ),
                )
                for idx in range(MERGE_RESULT_LIMIT + 3)
            ],
        )
    ]

    merged, _ = _merge_ranked_channel_bundles_explain(bundles)

    assert len(merged) == MERGE_RESULT_LIMIT


def test_signals_from_channel_bundles_preserve_channel_evidence_deterministically() -> (
    None
):
    """
    Normalize current channel evidence into ordered retrieval signals.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts signal adapters preserve producer attribution,
        capability names, deduped channel rank, and deterministic order.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "codira.beta", "run", "src/b.py", 20)
    bundles = [
        (
            "semantic",
            [
                (5.0, beta),
                (4.0, beta),
            ],
        ),
        (
            "symbol",
            [
                (9.0, alpha),
                (8.0, alpha),
            ],
        ),
    ]
    producers = _query_producers("cache invalidation", bundles)

    signals = _signals_from_channel_bundles(bundles, producers=producers)

    assert [(signal.target, signal.kind) for signal in signals] == [
        (alpha, "exact_symbol"),
        (beta, "text_match"),
    ]
    assert signals[0].producer_name == "query-channel-symbol"
    assert signals[0].capability_name == "symbol_lookup"
    assert signals[0].rank == 1
    assert signals[0].strength == 9.0
    assert signals[1].producer_name == "query-channel-semantic"
    assert signals[1].capability_name == "semantic_text"
    assert signals[1].rank == 1
    assert signals[1].strength == 5.0


def test_signals_from_channel_bundles_map_embedding_and_task_capabilities() -> None:
    """
    Preserve capability attribution for embedding and task-specialized channels.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts embedding and test channels normalize to the expected
        signal families and capability names.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "tests.alpha", "run_test", "tests/test_a.py", 20)
    bundles = [
        ("test", [(7.0, beta)]),
        ("embedding", [(6.5, alpha)]),
    ]
    producers = _query_producers("cache invalidation tests", bundles)

    signals = _signals_from_channel_bundles(bundles, producers=producers)

    assert [(signal.family, signal.capability_name) for signal in signals] == [
        ("semantic", "embedding_similarity"),
        ("task", "task_specialization"),
    ]
    assert signals[0].kind == "embedding_similarity"
    assert signals[0].channel_name == "embedding"
    assert signals[1].kind == "text_match"
    assert signals[1].channel_name == "test"


def test_collect_retrieval_signals_uses_known_channel_producers_only() -> None:
    """
    Collect signals generically through capability-aware producer inspection.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts channel producers contribute signals while
        enrichment-only producers remain diagnostics-only during Phase 5.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "tests.alpha", "run_test", "tests/test_a.py", 20)
    bundles = [
        ("symbol", [(9.0, alpha)]),
        ("test", [(7.0, beta)]),
    ]
    producers = _query_producers("cache invalidation tests", bundles)

    signals, diagnostics = _collect_retrieval_signals(bundles, producers=producers)

    assert [(signal.channel_name, signal.capability_name) for signal in signals] == [
        ("symbol", "symbol_lookup"),
        ("test", "task_specialization"),
    ]
    assert diagnostics == {
        "total_signals": 2,
        "families": {"lexical": 1, "task": 1},
        "capabilities": {"symbol_lookup": 1, "task_specialization": 1},
        "used_producers": ["query-channel-symbol", "query-channel-test"],
        "ignored_producers": [
            "query-enrichment-call-graph",
            "query-enrichment-references",
        ],
    }


def test_graph_expansion_still_keeps_enrichment_producers_out_of_initial_collection() -> (
    None
):
    """
    Keep graph enrichments diagnostics-only before expansion contributes signals.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the extracted graph enrichment path does not change
        initial capability-gated collection semantics.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    bundles = [("symbol", [(9.0, alpha)])]
    producers = _query_producers("architecture graph cache flow", bundles)

    signals, diagnostics = _collect_retrieval_signals(bundles, producers=producers)

    assert [signal.producer_name for signal in signals] == ["query-channel-symbol"]
    ignored_producers = diagnostics["ignored_producers"]

    assert isinstance(ignored_producers, list)
    assert "query-enrichment-call-graph" in ignored_producers


def test_bounded_graph_retrieval_signals_promote_graph_evidence_into_ranking() -> None:
    """
    Convert repeated raw graph evidence into bounded ranking-ready signals.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts graph evidence gains pseudo-channel metadata while
        keeping the bounded per-producer cap and deterministic ordering.
    """
    seed = _symbol("function", "pkg.seed", "search", "src/seed.py", 10)
    alpha = _symbol("function", "pkg.alpha", "run", "src/a.py", 20)
    beta = _symbol("function", "pkg.beta", "build", "src/b.py", 30)

    ranked = _bounded_graph_retrieval_signals(
        [
            CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                kind="relation",
                target=alpha,
                source_symbol=seed,
                distance=1,
            ),
            CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                kind="relation",
                target=alpha,
                source_symbol=seed,
                distance=1,
            ),
            CALL_GRAPH_RETRIEVAL_PRODUCER.build_signal(
                kind="relation",
                target=beta,
                source_symbol=seed,
                distance=2,
            ),
            REFERENCE_RETRIEVAL_PRODUCER.build_signal(
                kind="relation",
                target=beta,
                source_symbol=seed,
                distance=1,
            ),
        ]
    )

    assert [(signal.channel_name, signal.target, signal.rank) for signal in ranked] == [
        ("call_graph", alpha, 1),
        ("call_graph", beta, 2),
        ("references", beta, 1),
    ]
    assert ranked[0].strength == 1.1
    assert ranked[1].strength == 0.5
    assert ranked[2].strength == 1.0


def test_rank_signals_with_provenance_matches_channel_merge_contract() -> None:
    """
    Preserve current merge behavior when ranking from normalized signals.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the signal aggregator reproduces the existing merge
        ordering and provenance for one mixed lexical/semantic fixture.
    """
    alpha = _symbol("function", "codira.alpha", "run", "src/a.py", 10)
    beta = _symbol("function", "codira.beta", "run", "src/b.py", 20)
    bundles = [
        (
            "semantic",
            [
                (5.0, beta),
                (4.0, beta),
            ],
        ),
        (
            "symbol",
            [
                (9.0, alpha),
                (8.0, alpha),
            ],
        ),
    ]
    producers = _query_producers("cache invalidation", bundles)
    signals, _diagnostics = _collect_retrieval_signals(bundles, producers=producers)

    ranked, provenance = _rank_signals_with_provenance(signals)

    assert ranked == [(alpha, 1.75), (beta, 1.75)]
    assert provenance[alpha] == {
        "channels": {"symbol": 9.0},
        "families": {"lexical": 9.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.0,
        "role_bonus": 0.75,
        "merge_score": 1.75,
        "winner": "symbol",
    }
    assert provenance[beta] == {
        "channels": {"semantic": 5.0},
        "families": {"semantic": 5.0},
        "rrf_score": 1.0,
        "evidence_bonus": 0.0,
        "role_bonus": 0.75,
        "merge_score": 1.75,
        "winner": "semantic",
    }


def test_diversify_merged_symbols_caps_one_symbol_per_file() -> None:
    """
    Keep one file from monopolizing the merged top-symbol block.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts later files are allowed in once an earlier file
        already contributed one symbol.
    """
    ranked = [
        _symbol("function", "codira.alpha", "first", "src/a.py", 10),
        _symbol("function", "codira.alpha", "second", "src/a.py", 20),
        _symbol("function", "codira.beta", "run", "src/b.py", 30),
    ]

    diversified = _diversify_merged_symbols(ranked)

    assert diversified[:2] == [ranked[0], ranked[2]]


def test_diversify_merged_symbols_limits_test_role_monopoly() -> None:
    """
    Prevent test files from crowding out implementation results by default.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts excess test-role symbols are deferred until an
        implementation symbol is included.
    """
    ranked = [
        _symbol("function", "tests.alpha", "one", "tests/test_a.py", 10),
        _symbol("function", "tests.beta", "two", "tests/test_b.py", 20),
        _symbol("function", "tests.gamma", "three", "tests/test_c.py", 30),
        _symbol("function", "codira.core", "run", "src/core.py", 40),
    ]

    diversified = _diversify_merged_symbols(ranked)

    assert diversified[:3] == [ranked[0], ranked[1], ranked[3]]


def test_diversify_merged_symbols_limits_language_monopoly_when_mixed() -> None:
    """
    Prevent one language family from crowding out another in mixed results.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts a C result is admitted during primary selection when
        Python otherwise dominates a mixed-language ranked list.
    """
    ranked = [
        _symbol("function", "pkg.alpha", "one", "src/a.py", 10),
        _symbol("function", "pkg.beta", "two", "src/b.py", 20),
        _symbol("function", "pkg.gamma", "three", "src/c.py", 30),
        _symbol("function", "pkg.delta", "four", "src/d.py", 40),
        _symbol("function", "pkg.epsilon", "five", "src/e.py", 50),
        _symbol("function", "native.sample", "helper", "native/sample.c", 60),
    ]

    diversified = _diversify_merged_symbols(ranked)

    assert diversified[:5] == [ranked[0], ranked[1], ranked[2], ranked[3], ranked[5]]


def test_diversify_merged_symbols_explain_reports_selected_and_deferred() -> None:
    """
    Expose deterministic diversity diagnostics for explain mode.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts selected stages and deferred reasons are recorded.
    """
    ranked = [
        _symbol("function", "tests.alpha", "one", "tests/test_a.py", 10),
        _symbol("function", "tests.beta", "two", "tests/test_b.py", 20),
        _symbol("function", "tests.gamma", "three", "tests/test_c.py", 30),
        _symbol("function", "codira.core", "run", "src/core.py", 40),
    ]

    diversified, diagnostics = _diversify_merged_symbols_explain(ranked)

    assert diversified[:3] == [ranked[0], ranked[1], ranked[3]]
    assert diagnostics["selected"][0]["selection_stage"] == "primary"
    assert diagnostics["selected"][0]["language"] == "python"
    assert diagnostics["selected"][2]["selection_stage"] == "primary"
    assert diagnostics["deferred"][0]["reason"] == "role_cap"


def test_diversify_merged_symbols_explain_does_not_requeue_deferred_file_caps() -> None:
    """
    Keep deferred-stage file caps from mutating the active iteration list.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts deferred file-cap entries remain diagnostics only and
        do not loop indefinitely during deferred selection.
    """
    ranked = [
        _symbol("function", "pkg.alpha", "one", "src/shared.py", 10),
        _symbol("function", "pkg.alpha", "two", "src/shared.py", 20),
        _symbol("function", "pkg.beta", "run", "src/beta.py", 30),
    ]

    diversified, diagnostics = _diversify_merged_symbols_explain(ranked)

    assert diversified == [ranked[0], ranked[2]]
    assert diagnostics["deferred"] == [
        {
            "type": "function",
            "module": "pkg.alpha",
            "name": "two",
            "file": "src/shared.py",
            "lineno": 20,
            "role": "implementation",
            "language": "python",
            "reason": "file_cap",
        }
    ]


def test_diversify_merged_symbols_explain_reports_language_cap() -> None:
    """
    Surface language-cap deferrals in explain diagnostics.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts mixed-language deferrals record language metadata and
        the dedicated deferral reason.
    """
    ranked = [
        _symbol("function", "pkg.alpha", "one", "src/a.py", 10),
        _symbol("function", "pkg.beta", "two", "src/b.py", 20),
        _symbol("function", "pkg.gamma", "three", "src/c.py", 30),
        _symbol("function", "pkg.delta", "four", "src/d.py", 40),
        _symbol("function", "pkg.epsilon", "five", "src/e.py", 50),
        _symbol("function", "native.sample", "helper", "native/sample.c", 60),
    ]

    diversified, diagnostics = _diversify_merged_symbols_explain(ranked)

    assert diversified[:5] == [ranked[0], ranked[1], ranked[2], ranked[3], ranked[5]]
    assert diagnostics["selected"][4]["language"] == "c"
    assert diagnostics["deferred"][0] == {
        "type": "function",
        "module": "pkg.epsilon",
        "name": "five",
        "file": "src/e.py",
        "lineno": 50,
        "role": "implementation",
        "language": "python",
        "reason": "language_cap",
    }
