"""End-to-end checks for source-first C-family persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from codira_backend_duckdb import DuckDBIndexBackend
from codira_backend_sqlite import SQLiteIndexBackend

from codira.indexer import index_repo
from codira.query.exact import EdgeQueryRequest, find_call_edges, find_symbol
from codira.registry import reset_plugin_registry_caches

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
@pytest.mark.parametrize("language", ["c", "cpp"], ids=["c-source", "cpp-source"])
def test_source_only_conditional_occurrences_and_ambiguous_calls_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    backend_name: str,
    language: str,
) -> None:
    """Persist both conditional branches and leave ambiguous calls unresolved.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary source repository and backend index root.
    monkeypatch : pytest.MonkeyPatch
        Selects one backend for indexing and persisted queries.
    backend_name : str
        First-party structural backend to exercise.
    language : str
        C-family source analyzer under test.

    Returns
    -------
    None
        The test verifies both source-written branch occurrences and unresolved
        calls through queries backed by the persisted index.
    """
    root = tmp_path
    control_dir = root / ".codira"
    control_dir.mkdir()
    (control_dir / "config.toml").write_text(
        f'[backend]\nname = "{backend_name}"\n\n[embeddings]\nenabled = false\n',
        encoding="utf-8",
    )
    native_dir = root / "native"
    native_dir.mkdir()
    source_path = native_dir / f"conditional.{language}"
    prefix = f"{language}_"
    condition = "C_SOURCE_BRANCH" if language == "c" else "CPP_SOURCE_BRANCH"
    suffix = "(void)" if language == "c" else "()"
    source_path.write_text(
        f"#if {condition}\n"
        f"int {prefix}selected{suffix} {{ return 1; }}\n"
        "#else\n"
        f"long {prefix}selected{suffix} {{ return 2; }}\n"
        "#endif\n"
        f"int {prefix}dispatch{suffix} {{ return {prefix}selected(); }}\n",
        encoding="utf-8",
    )
    if language == "cpp":
        with source_path.open("a", encoding="utf-8") as source_file:
            source_file.write(
                "#if CPP_CLASS_BRANCH\n"
                "class cpp_choice {};\n"
                "#else\n"
                "class cpp_choice {};\n"
                "#endif\n"
            )

    monkeypatch.setenv("CODIRA_INDEX_BACKEND", backend_name)
    reset_plugin_registry_caches()
    backend = SQLiteIndexBackend() if backend_name == "sqlite" else DuckDBIndexBackend()
    backend.initialize(root)
    try:
        report = index_repo(root, full=True)

        assert report.failed == 0
        assert report.indexed == 1
        assert not (root / "compile_commands.json").exists()

        occurrences = find_symbol(root, f"{prefix}selected")
        assert [(row[3], row[4]) for row in occurrences] == [
            (str(source_path), 2),
            (str(source_path), 4),
        ]
        if language == "cpp":
            class_occurrences = find_symbol(root, "cpp_choice")
            assert [(row[0], row[3], row[4]) for row in class_occurrences] == [
                ("class", str(source_path), 8),
                ("class", str(source_path), 10),
            ]

        connection = backend.open_connection(root)
        try:
            written_calls = connection.execute(
                "SELECT target, target_identity_value, resolution_mode "
                "FROM call_records WHERE owner_name = ? ORDER BY lineno",
                (f"{prefix}dispatch",),
            ).fetchall()
        finally:
            connection.close()
        assert written_calls == [(f"{prefix}selected", None, "exact")]

        edges = find_call_edges(EdgeQueryRequest(root=root, name=f"{prefix}dispatch"))
        assert len(edges) == 1
        assert edges[0][1] == f"{prefix}dispatch"
        assert edges[0][4] is None
        assert edges[0][5] is None
        assert edges[0][7] == f"{prefix}selected"
        assert edges[0][8] == 0
    finally:
        reset_plugin_registry_caches()
        if backend_name == "duckdb":
            cast("DuckDBIndexBackend", backend)._close_cached_connections()
