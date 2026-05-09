"""Deterministic tests for static call-graph indexing and inspection.

Responsibilities
----------------
- Build small multi-module fixtures that exercise imports, callable references, and example call sites.
- Index the fixtures, query call edges, and assert deterministic ordering plus deduplication.
- Validate helper discovery features such as imported-call resolution and include edges.

Design principles
-----------------
Fixtures stay small, deterministic, and fully described so call-graph regressions point to indexing logic.

Architectural role
------------------
This module belongs to the **verification layer** and protects call-graph expectations used by query rendering.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

from codira.cli import build_parser, main
from codira.indexer import index_repo
from codira.query.context import ContextRequest, context_for
from codira.query.exact import (
    EdgeQueryRequest,
    find_call_edges,
    find_callable_refs,
    find_include_edges,
)
from codira.query.graph_enrichment import (
    GraphExpansionRequest,
    _select_graph_expansion_seeds,
)
from codira.storage import get_db_path, init_db


def _write_fixture(root: Path) -> None:
    """
    Write a small multi-module package used for call-graph tests.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files are created under ``root``.
    """
    pkg = root / "pkg"
    pkg.mkdir()

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text(
        '"""Helpers for import resolution tests."""\n'
        "\n"
        "def imported_helper():\n"
        '    """Return a constant value."""\n'
        "    return 1\n",
        encoding="utf-8",
    )
    (pkg / "a.py").write_text(
        '"""Call-graph fixture module."""\n'
        "\n"
        "from pkg.b import imported_helper as external\n"
        "import pkg.b as helpers\n"
        "\n"
        "def helper(value=0):\n"
        '    """Return the given value."""\n'
        "    return value\n"
        "\n"
        "def dynamic(callback):\n"
        '    """Trigger unresolved callback calls."""\n'
        "    callback()\n"
        "    callback()\n"
        "    return 1\n"
        "\n"
        "def caller():\n"
        '    """Exercise same-module static calls."""\n'
        "    helper()\n"
        "    helper(1)\n"
        "    return dynamic(helper)\n"
        "\n"
        "def registry():\n"
        '    """Return callable references without invoking them."""\n'
        "    return {\n"
        '        "local": helper,\n'
        '        "imported": external,\n'
        '        "method": Demo.helper,\n'
        "    }\n"
        "\n"
        "def imported_caller():\n"
        '    """Exercise straightforward imported call resolution."""\n'
        "    external()\n"
        "    helpers.imported_helper()\n"
        "    return 1\n"
        "\n"
        "class Demo:\n"
        "    def helper(self):\n"
        '        """Return a constant value."""\n'
        "        return 1\n"
        "\n"
        "    def caller(self):\n"
        '        """Exercise self method resolution."""\n'
        "        self.helper()\n"
        "        self.helper()\n"
        "        return 1\n",
        encoding="utf-8",
    )


def test_call_edges_are_resolved_and_deduplicated(tmp_path: Path) -> None:
    """
    Index a fixture package and assert deterministic call-edge rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts exact stored call-edge rows and helper lookups.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        rows = conn.execute("""
            SELECT caller_module, caller_name, callee_module, callee_name, resolved
            FROM call_edges
            ORDER BY
                caller_module,
                caller_name,
                COALESCE(callee_module, ''),
                COALESCE(callee_name, ''),
                resolved
            """).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("pkg.a", "Demo.caller", "pkg.a", "Demo.helper", 1),
        ("pkg.a", "caller", "pkg.a", "dynamic", 1),
        ("pkg.a", "caller", "pkg.a", "helper", 1),
        ("pkg.a", "dynamic", None, None, 0),
        ("pkg.a", "imported_caller", "pkg.b", "imported_helper", 1),
    ]

    assert find_call_edges(
        EdgeQueryRequest(root=tmp_path, name="caller", module="pkg.a")
    ) == [
        ("pkg.a", "caller", "pkg.a", "dynamic", 1),
        ("pkg.a", "caller", "pkg.a", "helper", 1),
    ]
    assert find_call_edges(
        EdgeQueryRequest(
            root=tmp_path,
            name="imported_helper",
            module="pkg.b",
            incoming=True,
        )
    ) == [
        ("pkg.a", "imported_caller", "pkg.b", "imported_helper", 1),
    ]

    assert find_callable_refs(
        EdgeQueryRequest(root=tmp_path, name="registry", module="pkg.a")
    ) == [
        ("pkg.a", "registry", "pkg.a", "Demo.helper", 1),
        ("pkg.a", "registry", "pkg.a", "helper", 1),
        ("pkg.a", "registry", "pkg.b", "imported_helper", 1),
    ]
    assert find_callable_refs(
        EdgeQueryRequest(
            root=tmp_path,
            name="helper",
            module="pkg.a",
            incoming=True,
        )
    ) == [
        ("pkg.a", "registry", "pkg.a", "helper", 1),
    ]


def test_chained_attribute_calls_keep_distinct_semantics(tmp_path: Path) -> None:
    """
    Preserve distinct raw call records for chained dynamic attribute calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts that chained calls produce distinct raw records and
        index without storage collisions.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "chain.py").write_text(
        '"""Fixture covering chained dynamic attribute calls."""\n'
        "\n"
        "def chained(text, line, value):\n"
        '    """Exercise chained dynamic attribute calls."""\n'
        "    text.replace(\n"
        '        "\\\\", r"\\\\"\n'
        '    ).replace("{", r"\\\\{").replace("}", r"\\\\}")\n'
        '    line[len("file:") :].strip().strip(\'"\')\n'
        "    str(value).strip().lower()\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        rows = conn.execute("""
            SELECT kind, base, target, lineno, col_offset
            FROM call_records
            WHERE owner_module = 'pkg.chain' AND owner_name = 'chained'
            ORDER BY lineno, col_offset, kind, base, target
            """).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("attribute", "text", "replace", 5, 9),
        ("attribute", "", "replace", 7, 6),
        ("attribute", "", "replace", 7, 27),
        ("name", "", "len", 8, 9),
        ("attribute", "", "strip", 8, 25),
        ("attribute", "", "strip", 8, 33),
        ("name", "", "str", 9, 4),
        ("attribute", "", "strip", 9, 15),
        ("attribute", "", "lower", 9, 23),
    ]


def test_calls_cli_prints_incoming_edges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify the CLI inspection path for incoming call edges.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the printed incoming edge line.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "imported_helper",
            "--module",
            "pkg.b",
            "--incoming",
        ],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "pkg.a.imported_caller -> pkg.b.imported_helper"


def test_calls_cli_tree_prints_bounded_outgoing_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render a bounded outgoing call tree without changing flat call output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts deterministic tree rendering for a small caller
        neighborhood.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "caller",
            "--tree",
            "--max-depth",
            "2",
            "--max-nodes",
            "10",
        ],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip().splitlines() == [
        "pkg.a.caller",
        "  -> pkg.a.dynamic",
        "    -> <unresolved>",
        "  -> pkg.a.helper",
    ]


def test_refs_cli_prints_incoming_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify the CLI inspection path for incoming callable references.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the printed incoming reference line.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "helper",
            "--module",
            "pkg.a",
            "--incoming",
        ],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "pkg.a.registry => pkg.a.helper"


def test_refs_cli_tree_prints_bounded_incoming_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render a bounded incoming reference tree while preserving flat refs output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts deterministic tree rendering for a small incoming
        reference neighborhood.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "helper",
            "--module",
            "pkg.a",
            "--incoming",
            "--tree",
            "--max-depth",
            "2",
            "--max-nodes",
            "10",
        ],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert captured.out.strip().splitlines() == [
        "pkg.a.helper",
        "  <= pkg.a.registry",
    ]


def test_c_call_edges_are_indexed_for_same_module_functions(tmp_path: Path) -> None:
    """
    Ensure lightweight C call extraction reaches the stored call-edge graph.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts same-module C call-edge resolution.
    """
    module = tmp_path / "native" / "sample.c"
    module.parent.mkdir()
    module.write_text(
        "static int helper(int value) {\n"
        "    return normalize(value);\n"
        "}\n"
        "\n"
        "int public_api(int input) {\n"
        "    return helper(input);\n"
        "}\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    assert find_call_edges(
        EdgeQueryRequest(root=tmp_path, name="public_api", module="native.sample")
    ) == [
        ("native.sample", "public_api", "native.sample", "helper", 1),
    ]
    assert find_call_edges(
        EdgeQueryRequest(
            root=tmp_path,
            name="helper",
            module="native.sample",
            incoming=True,
        )
    ) == [("native.sample", "public_api", "native.sample", "helper", 1)]


def test_top_level_help_includes_examples_and_calls_command() -> None:
    """
    Verify the top-level help advertises key commands and examples.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts key help text fragments.
    """
    parser = build_parser()
    help_text = parser.format_help()

    assert 'codira emb "schema migration rules"' in help_text
    assert "codira calls caller" in help_text
    assert "codira refs _retrieve_script_candidates --incoming" in help_text
    assert "codira ctx --prompt" in help_text
    assert 'codira ctx "find schema migration logic"' in help_text
    assert "audit" in help_text


def test_context_for_expands_related_cross_module_graph_symbols(
    tmp_path: Path,
) -> None:
    """
    Ensure context expansion pulls in cross-module graph-related symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts graph-derived expansion from call and ref data.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    imported_data = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="imported_helper",
                as_json=True,
            )
        )
    )
    registry_data = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="registry",
                as_json=True,
            )
        )
    )

    imported_related = {
        (row["module"], row["name"])
        for row in imported_data["top_matches"] + imported_data["module_expansion"]
    }
    registry_related = {
        (row["module"], row["name"])
        for row in registry_data["top_matches"] + registry_data["module_expansion"]
    }

    assert ("pkg.a", "imported_caller") in imported_related
    assert ("pkg.a", "registry") in imported_related
    assert ("pkg.b", "imported_helper") in registry_related


def test_context_for_explain_marks_call_graph_and_reference_producers_as_used(
    tmp_path: Path,
) -> None:
    """
    Preserve explain-mode producer attribution for graph expansion evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts call-graph and callable-reference enrichments move
        from diagnostics-only to used producers when they emit graph signals.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    payload = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="imported_helper",
                as_json=True,
                explain=True,
            )
        )
    )
    signal_collection = payload["explain"]["signal_collection"]

    assert "graph" in signal_collection["families"]
    assert "graph_relations" in signal_collection["capabilities"]
    assert "query-enrichment-call-graph" in signal_collection["used_producers"]
    assert "query-enrichment-references" in signal_collection["used_producers"]


def test_context_for_uses_bounded_graph_retrieval_to_score_top_matches(
    tmp_path: Path,
) -> None:
    """
    Add bounded graph evidence to ranked top matches during retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts top matches carry explicit graph-family retrieval
        support once bounded graph scoring is integrated.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    payload = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="helper registry",
                as_json=True,
                explain=True,
            )
        )
    )

    top_matches = {(row["module"], row["name"]) for row in payload["top_matches"]}
    signal_collection = payload["explain"]["signal_collection"]
    signal_merge = payload["explain"]["signal_merge"]
    signal_support = {(entry["module"], entry["name"]): entry for entry in signal_merge}

    assert ("pkg.a", "registry") in top_matches
    assert "graph" in signal_collection["families"]
    assert signal_support[("pkg.a", "registry")]["families"]["graph"] > 0
    assert (
        "query-enrichment-references"
        in signal_support[("pkg.a", "registry")]["producers"]
    )


def test_c_include_edges_are_queryable_and_expand_context(tmp_path: Path) -> None:
    """
    Expose direct local include edges through exact queries and context.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts include-edge lookup and include-graph context
        expansion for mixed C header/source fixtures.
    """
    native = tmp_path / "native"
    native.mkdir()
    (native / "sample.h").write_text(
        "struct Node { int value; };\n",
        encoding="utf-8",
    )
    (native / "sample.c").write_text(
        '#include "native/sample.h"\n\nint public_api(void) {\n    return 1;\n}\n',
        encoding="utf-8",
    )
    (native / "consumer.c").write_text(
        '#include "native/sample.h"\n\nint consume_node(void) {\n    return 1;\n}\n',
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    assert find_include_edges(
        EdgeQueryRequest(root=tmp_path, name="native.sample")
    ) == [
        ("native.sample", "native/sample.h", "include_local", 1),
    ]
    assert find_include_edges(
        EdgeQueryRequest(
            root=tmp_path,
            name="native/sample.h",
            incoming=True,
        )
    ) == [
        ("native.consumer", "native/sample.h", "include_local", 1),
        ("native.sample", "native/sample.h", "include_local", 1),
    ]

    header_data = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="Node",
                as_json=True,
            )
        )
    )
    related = {
        (row["module"], row["name"])
        for row in header_data["top_matches"] + header_data["module_expansion"]
    }

    assert ("native.sample", "public_api") in related
    assert ("native.consumer", "consume_node") in related


def test_c_include_graph_expands_transitively(tmp_path: Path) -> None:
    """
    Follow deterministic transitive local include chains during expansion.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts include-graph expansion reaches symbols behind a
        second local header hop.
    """
    native = tmp_path / "native"
    native.mkdir()
    (native / "base.h").write_text(
        "struct BaseNode { int value; };\n",
        encoding="utf-8",
    )
    (native / "mid.h").write_text(
        '#include "native/base.h"\n\nstruct MidNode { int value; };\n',
        encoding="utf-8",
    )
    (native / "sample.c").write_text(
        '#include "native/mid.h"\n\nint public_api(void) {\n    return 1;\n}\n',
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    payload = json.loads(
        context_for(ContextRequest(root=tmp_path, query="public_api", as_json=True))
    )
    related = {
        (row["module"], row["name"])
        for row in payload["top_matches"] + payload["module_expansion"]
    }

    assert ("native.mid", "MidNode") in related
    assert ("native.base", "BaseNode") in related


def test_c_include_graph_explain_reports_expansion_entries(tmp_path: Path) -> None:
    """
    Expose include-graph expansion provenance in explain-mode JSON output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts include-graph expansion entries are reported with
        deterministic edge metadata.
    """
    native = tmp_path / "native"
    native.mkdir()
    (native / "sample.h").write_text(
        "struct Node { int value; };\n",
        encoding="utf-8",
    )
    (native / "sample.c").write_text(
        '#include "native/sample.h"\n\nint public_api(void) {\n    return 1;\n}\n',
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    payload = json.loads(
        context_for(
            ContextRequest(
                root=tmp_path,
                query="public_api",
                as_json=True,
                explain=True,
            )
        )
    )
    explain = payload["explain"]
    expansion = explain["expansion"]
    graph_budget = expansion["graph_budget"]
    include_graph = expansion["include_graph"]
    signal_collection = explain["signal_collection"]

    assert graph_budget[0] == {
        "top_match_rank": 1,
        "module": "native.sample",
        "name": "public_api",
        "type": "function",
        "include_graph_selected": True,
        "include_graph_reason": "selected",
        "relation_selected": True,
        "relation_reason": "selected",
    }
    assert any(
        entry["name"] == "Node"
        and entry["include_graph_selected"] is True
        and entry["relation_reason"] == "not_callable"
        for entry in graph_budget
    )
    assert {
        "seed_module": "native.sample",
        "via_module": "native.sample",
        "target_name": "native/sample.h",
        "kind": "include_local",
        "direction": "outgoing",
        "expanded_module": "native.sample",
        "expanded_name": "Node",
    } in include_graph
    assert "graph" in signal_collection["families"]
    assert "graph_relations" in signal_collection["capabilities"]
    assert "query-enrichment-include-graph" in signal_collection["used_producers"]


def test_graph_expansion_seed_selection_is_ranked_and_bounded() -> None:
    """
    Select deterministic graph-expansion seeds with per-kind hard limits.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts ranked seed selection for include and relation
        expansion plus deterministic skip reasons after the budgets are
        exhausted.
    """
    top_matches = [
        ("function", "pkg.alpha", "alpha", "src/alpha.c", 10),
        ("function", "pkg.beta", "beta", "src/beta.py", 20),
        ("method", "pkg.gamma", "gamma", "src/gamma.c", 30),
        ("function", "pkg.delta", "delta", "src/delta.py", 40),
        ("function", "pkg.epsilon", "epsilon", "src/epsilon.c", 50),
        ("class", "pkg.zeta", "Zeta", "src/zeta.c", 60),
    ]

    conn = sqlite3.connect(":memory:")
    try:
        include_seeds, relation_seeds, diagnostics = _select_graph_expansion_seeds(
            GraphExpansionRequest(
                root=Path("/tmp/repo"),
                top_matches=top_matches,
                conn=conn,
                include_include_graph=True,
                include_references=True,
                prefix=None,
                expanded=[],
                seen_symbols=set(),
                graph_signals=None,
                classify_file_language=lambda file_path: (
                    "c" if file_path.endswith(".c") else "python"
                ),
                classify_file_role=lambda _file_path, _module_name: "implementation",
                include_target_module_name=lambda _target_name, _kind: None,
                symbols_in_module=lambda _root, _module_name: [],
            )
        )
    finally:
        conn.close()

    assert include_seeds == [
        ("function", "pkg.alpha", "alpha", "src/alpha.c", 10),
        ("method", "pkg.gamma", "gamma", "src/gamma.c", 30),
    ]
    assert relation_seeds == [
        ("function", "pkg.alpha", "alpha", "src/alpha.c", 10),
        ("function", "pkg.beta", "beta", "src/beta.py", 20),
        ("method", "pkg.gamma", "gamma", "src/gamma.c", 30),
        ("function", "pkg.delta", "delta", "src/delta.py", 40),
    ]
    assert diagnostics == [
        {
            "top_match_rank": 1,
            "module": "pkg.alpha",
            "name": "alpha",
            "type": "function",
            "include_graph_selected": True,
            "include_graph_reason": "selected",
            "relation_selected": True,
            "relation_reason": "selected",
        },
        {
            "top_match_rank": 2,
            "module": "pkg.beta",
            "name": "beta",
            "type": "function",
            "include_graph_selected": False,
            "include_graph_reason": "not_c_language",
            "relation_selected": True,
            "relation_reason": "selected",
        },
        {
            "top_match_rank": 3,
            "module": "pkg.gamma",
            "name": "gamma",
            "type": "method",
            "include_graph_selected": True,
            "include_graph_reason": "selected",
            "relation_selected": True,
            "relation_reason": "selected",
        },
        {
            "top_match_rank": 4,
            "module": "pkg.delta",
            "name": "delta",
            "type": "function",
            "include_graph_selected": False,
            "include_graph_reason": "not_c_language",
            "relation_selected": True,
            "relation_reason": "selected",
        },
        {
            "top_match_rank": 5,
            "module": "pkg.epsilon",
            "name": "epsilon",
            "type": "function",
            "include_graph_selected": False,
            "include_graph_reason": "seed_limit",
            "relation_selected": False,
            "relation_reason": "seed_limit",
        },
        {
            "top_match_rank": 6,
            "module": "pkg.zeta",
            "name": "Zeta",
            "type": "class",
            "include_graph_selected": False,
            "include_graph_reason": "seed_limit",
            "relation_selected": False,
            "relation_reason": "not_callable",
        },
    ]


def test_context_for_help_shows_incompatibility_and_examples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify subcommand help exposes examples and parser-level constraints.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Pytest capture fixture used to inspect emitted help text.

    Returns
    -------
    None
        The test asserts help text and parser enforcement for context modes.
    """
    with pytest.raises(SystemExit) as help_exit:
        build_parser().parse_args(["ctx", "-h"])

    assert help_exit.value.code == 0

    captured = capsys.readouterr()
    assert "--json | --prompt | --explain" in captured.out
    assert "codira ctx --explain" in captured.out

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["ctx", "--prompt", "--explain", "static call graph"])

    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["ctx", "--json", "--prompt", "static call graph"])

    assert exc.value.code == 2


def test_query_subcommand_help_includes_json_examples(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify exact/query subcommands advertise JSON output in help text.

    Parameters
    ----------
    capsys : pytest.CaptureFixture[str]
        Pytest capture fixture used to inspect emitted help text.

    Returns
    -------
    None
        The test asserts JSON help text on representative subcommands.
    """
    expected_examples = {
        "sym": "codira sym build_parser --json",
        "emb": 'codira emb "schema migration rules" --json',
        "calls": "codira calls caller --json",
        "refs": "codira refs helper --json",
        "audit": "codira audit --json",
    }

    for command, example in expected_examples.items():
        with pytest.raises(SystemExit) as help_exit:
            build_parser().parse_args([command, "-h"])

        assert help_exit.value.code == 0
        output = capsys.readouterr().out
        assert "--json" in output
        assert example in output


def test_calls_cli_tree_json_reports_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Expose explicit truncation metadata for bounded tree traversal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts JSON tree output includes explicit node-cap
        truncation.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "caller",
            "--tree",
            "--max-depth",
            "2",
            "--max-nodes",
            "2",
            "--json",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "calls"
    assert payload["status"] == "ok"
    assert payload["query"] == {
        "name": "caller",
        "module": None,
        "incoming": False,
        "tree": True,
        "max_depth": 2,
        "max_nodes": 2,
        "prefix": None,
    }
    assert payload["truncated"] == {"depth": False, "nodes": True}
    assert payload["node_count"] == 2
    assert payload["edge_count"] == 1
    assert payload["results"] == [
        {
            "module": "pkg.a",
            "name": "caller",
            "display": "pkg.a.caller",
            "resolved": True,
            "incoming": False,
            "cycle": False,
            "children": [
                {
                    "module": "pkg.a",
                    "name": "dynamic",
                    "display": "pkg.a.dynamic",
                    "resolved": True,
                    "cycle": False,
                    "children": [],
                }
            ],
        }
    ]


def test_calls_cli_tree_dot_renders_bounded_graphviz_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render bounded call-tree traversal as Graphviz DOT.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts `calls --tree --dot` emits deterministic DOT with
        bounded traversal edges.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "caller",
            "--tree",
            "--dot",
            "--max-depth",
            "1",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "digraph codira_calls {" in output
    assert 'n0 [label="pkg.a.caller"];' in output
    assert 'n1 [label="pkg.a.dynamic"];' in output
    assert "n0 -> n1;" in output
    assert 'graph [label="truncated by max_depth", labelloc="b"];' in output


def test_refs_cli_tree_json_reports_truncation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Expose explicit truncation metadata for bounded ref-tree traversal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts JSON tree output includes explicit depth-cap
        truncation for incoming refs.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "helper",
            "--module",
            "pkg.a",
            "--incoming",
            "--tree",
            "--max-depth",
            "0",
            "--max-nodes",
            "10",
            "--json",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["command"] == "refs"
    assert payload["status"] == "ok"
    assert payload["truncated"] == {"depth": True, "nodes": False}
    assert payload["node_count"] == 1
    assert payload["edge_count"] == 0
    assert payload["results"] == [
        {
            "module": "pkg.a",
            "name": "helper",
            "display": "pkg.a.helper",
            "resolved": True,
            "incoming": True,
            "cycle": False,
            "children": [],
        }
    ]


def test_refs_cli_tree_dot_renders_incoming_graphviz_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Render bounded ref traversal as Graphviz DOT with incoming edge direction.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts incoming `refs --tree --dot` points owners toward the
        selected target.
    """
    _write_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "helper",
            "--module",
            "pkg.a",
            "--incoming",
            "--tree",
            "--dot",
            "--max-depth",
            "1",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out

    assert "digraph codira_refs {" in output
    assert 'n0 [label="pkg.a.helper"];' in output
    assert 'n1 [label="pkg.a.registry"];' in output
    assert "n1 -> n0;" in output


def test_calls_cli_dot_rejects_non_tree_and_json_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Reject unsupported DOT flag combinations at the parser boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture parser stderr.

    Returns
    -------
    None
        The test asserts `--dot` remains tree-only and plain-text only.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "calls", "caller", "--dot", "--json"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "--dot requires --tree for calls" in capsys.readouterr().err
