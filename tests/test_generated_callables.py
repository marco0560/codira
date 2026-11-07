"""Check generated callable persistence, retrieval and input freshness end to end.

Parameters
----------
None

Returns
-------
None
    Synthetic indexing controls, independent of original-file native admission.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from codira.config import profile_config, render_config_toml
from codira.generated import generated_provenance_payload
from codira.indexer import index_repo
from codira.query.evidence import expand_symbol, symbol_identity
from codira.query.exact import find_symbol
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import BackendQueryConnection


def _repository(root: Path, backend: str) -> Path:
    """Create a contained synthetic C++ repository with an explicit public profile.

    Parameters
    ----------
    root : pathlib.Path
        Test repository whose source and configuration are disposable.
    backend : str
        Independently distributed structural backend to exercise.

    Returns
    -------
    pathlib.Path
        Original source path used by real indexing and retrieval.
    """
    (root / "h.h").write_text("""#ifndef H
#define H
#define WRAP(T,N,A) decltype(NS::N) impl_##N asm(#N); decltype(NS::N) N [[gnu::alias(#N)]]; T impl_##N A
namespace NS { double f(double x); }
#endif
""")
    path = root / "main.cpp"
    path.write_text(
        '#include "h.h"\nnamespace NS {\nWRAP(double,f,(double x)) {\n  return target(x);\n}\n}\n'
    )
    payload = profile_config("default")
    payload["backend"] = {"name": backend}
    payload["embeddings"] = {"enabled": False, "similarity_index": "exact"}
    payload["plugins"] = {
        "disabled_analyzers": ["c"],
        "analyzer-cpp": {
            "include_paths": ["main.cpp"],
            "preprocessor_definitions": {"H": False, "NS": "ns"},
        },
    }
    config = root / ".codira/config.toml"
    config.parent.mkdir()
    config.write_text(render_config_toml(payload))
    return path


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_generated_provenance_survives_full_incremental_refresh_and_deletion(
    tmp_path: Path, backend_name: str
) -> None:
    """Roundtrip implementation, prototype and alias through real index operations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and backend state.
    backend_name : str
        SQLite or DuckDB plugin.

    Returns
    -------
    None
        Full-index buffering, incremental replacement, freshness and deletion work.
    """
    path = _repository(tmp_path, backend_name)
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)
    index_repo(tmp_path, full=True)
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        rows = conn.execute("SELECT payload FROM artifact_provenance").fetchall()
        assert len(rows) == 3
        assert sorted(
            str(generated_provenance_payload(str(r[0]))["role"]) for r in rows
        ) == ["alias", "definition", "prototype"]
    finally:
        backend.close_connection(conn)
    implementation = find_symbol(tmp_path, "ns::impl_f")[0]
    alias = find_symbol(tmp_path, "ns::f")[0]
    definition = expand_symbol(tmp_path, symbol_identity(tmp_path, implementation))
    alias_evidence = expand_symbol(tmp_path, symbol_identity(tmp_path, alias))
    assert definition["end_line"] == 5
    assert "return target(x)" in str(definition["source"])
    assert alias_evidence["start_line"] == alias_evidence["end_line"] == 3
    assert alias_evidence["source"] == "WRAP(double,f,(double x))"
    assert alias_evidence["source_kind"] == "macro_invocation"
    assert (
        cast("dict[str,object]", alias_evidence["generated_provenance"])["alias_target"]
        == "ns::impl_f"
    )
    assert len(cast("list[object]", definition["generated_declarations"])) == 1
    # Cached symbol source bytes alone are insufficient after a header changes.
    header = tmp_path / "h.h"
    header.write_text(header.read_text() + "// dependency changed\n")
    with pytest.raises(ValueError, match="inputs changed"):
        expand_symbol(tmp_path, symbol_identity(tmp_path, alias))
    index_repo(tmp_path)
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM artifact_provenance").fetchone() == (
            3,
        )
    finally:
        backend.close_connection(conn)
    backend.delete_paths(tmp_path, paths=[str(path)])
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM artifact_provenance").fetchone() == (
            0,
        )
    finally:
        backend.close_connection(conn)


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_full_index_replacement_clears_generated_provenance(
    tmp_path: Path, backend_name: str
) -> None:
    """Remove obsolete generated records when rebuilding to ordinary source.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and index state.
    backend_name : str
        Selected structural backend.

    Returns
    -------
    None
        Old generated identities cannot survive a full replacement.
    """
    path = _repository(tmp_path, backend_name)
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)
    index_repo(tmp_path, full=True)
    path.write_text("int ordinary() { return 1; }\n")
    index_repo(tmp_path, full=True)
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        assert conn.execute("SELECT COUNT(*) FROM artifact_provenance").fetchone() == (
            0,
        )
    finally:
        backend.close_connection(conn)


@pytest.mark.parametrize(
    "mutation", ["physical_paste", "escaping_origin", "alias_without_target", "version"]
)
def test_corrupt_generated_records_are_rejected(tmp_path: Path, mutation: str) -> None:
    """Reject forged physical spellings, escaping origins and invalid identity data.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository containing genuine generated metadata.
    mutation : str
        Deliberately wrong stored-artifact control.

    Returns
    -------
    None
        Corrupt records are never accepted as verified generated evidence.
    """
    _repository(tmp_path, "sqlite")
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)
    index_repo(tmp_path, full=True)
    conn = cast("BackendQueryConnection", backend.open_connection(tmp_path))
    try:
        rows = conn.execute("SELECT payload FROM artifact_provenance").fetchall()
        payload = next(
            json.loads(str(row[0]))
            for row in rows
            if json.loads(str(row[0]))["role"] == "alias"
        )
    finally:
        backend.close_connection(conn)
    if mutation == "physical_paste":
        token = payload["tokens"][0]
        token["operation"] = "paste"
        token["physical_spelling_span"] = token["anchor"]
    elif mutation == "escaping_origin":
        payload["inputs"][0]["source_path"] = "../escape.h"
    elif mutation == "alias_without_target":
        payload["alias_target"] = None
    else:
        payload["format_version"] = 99
    with pytest.raises(ValueError):
        generated_provenance_payload(json.dumps(payload))


def test_spawned_indexing_preserves_explicit_config_path(tmp_path: Path) -> None:
    """Use the caller's external profile in spawned analysis workers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source repository and separately selected configuration.

    Returns
    -------
    None
        Actual process indexing retains generated identities and provenance.
    """
    import tomllib

    from codira.config import IndexConcurrencyConfig, override_repo_config_path

    path = _repository(tmp_path, "sqlite")
    (tmp_path / "second.cpp").write_bytes(path.read_bytes())
    selected = tmp_path / "selected-profile.toml"
    (tmp_path / ".codira/config.toml").rename(selected)
    payload = tomllib.loads(selected.read_text())
    payload["plugins"]["analyzer-cpp"]["include_paths"] = ["main.cpp", "second.cpp"]
    selected.write_text(render_config_toml(payload))
    with override_repo_config_path(selected):
        backend = active_index_backend(root=tmp_path)
        backend.initialize(tmp_path)
        report = index_repo(
            tmp_path,
            full=True,
            analysis_concurrency=IndexConcurrencyConfig(
                strategy="process", max_workers=1, min_files=1
            ),
        )
        assert report.failed == 0, report.failures
        assert report.indexed == 2
        assert report.analysis_concurrency.effective_strategy == "process"
        assert find_symbol(tmp_path, "ns::impl_f")
        assert find_symbol(tmp_path, "ns::f")
