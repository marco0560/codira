"""Deterministic tests for the local embedding backend and retrieval channel.

Responsibilities
----------------
- Validate embedding determinism, storage of symbol embeddings, and candidate ranking behaviors.
- Use small fixtures to cover backend metadata, vector shape, and retrieval overlap.

Design principles
-----------------
Tests isolate embedding behaviors to avoid interference with other indexing heuristics.

Architectural role
------------------
This module belongs to the **semantic retrieval verification layer** that guards embedding stability.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from typing import TYPE_CHECKING

from codira.cli import main
from codira.indexer import (
    PendingEmbeddingRow,
    StoredEmbeddingRow,
    _flush_embedding_rows,
    index_repo,
)
from codira.query.exact import find_symbol
from codira.semantic import embeddings as embeddings_module
from codira.semantic.embeddings import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    EMBEDDING_BACKEND,
    EMBEDDING_DIM,
    EMBEDDING_VERSION,
    EmbeddingBackendError,
    embed_text,
    embed_texts,
)
from codira.semantic.search import embedding_candidates
from codira.storage import get_db_path, init_db

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _write_embedding_fixture(root: Path) -> None:
    """
    Write a small package used for embedding-channel tests.

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
    (pkg / "sample.py").write_text(
        '"""Embedding fixture module."""\n'
        "\n"
        "def validate_schema_rules():\n"
        '    """Validate schema migration rules for repository metadata."""\n'
        "    return 1\n"
        "\n"
        "def docstring_audit():\n"
        '    """Audit numpy docstring sections and required parameters."""\n'
        "    return 1\n",
        encoding="utf-8",
    )


def test_embed_text_is_deterministic_and_normalized() -> None:
    """
    Ensure the local embedding backend is deterministic and normalized.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts backend determinism and vector shape.
    """
    first = embed_text("schema migration rules")
    second = embed_text("schema migration rules")

    assert first == second
    assert len(first) == EMBEDDING_DIM
    assert round(sum(value * value for value in first), 6) == 1.0


def test_embed_texts_batches_inputs_and_preserves_blank_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Batch non-blank texts while preserving deterministic zero vectors for blanks.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control the embedding model loader.

    Returns
    -------
    None
        The test asserts batching, argument forwarding, and blank-text handling.
    """

    class _FakeVector:
        def __init__(self, values: list[float]) -> None:
            self._values = values

        def tolist(self) -> list[float]:
            return list(self._values)

    class _FakeModel:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], int, bool, bool]] = []

        def encode(
            self,
            sentences: list[str],
            *,
            batch_size: int,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> list[_FakeVector]:
            assert show_progress_bar is False
            self.calls.append(
                (
                    list(sentences),
                    batch_size,
                    convert_to_numpy,
                    normalize_embeddings,
                )
            )
            return [
                _FakeVector([float(index + 1)] * EMBEDDING_DIM)
                for index, _sentence in enumerate(sentences)
            ]

        def get_sentence_embedding_dimension(self) -> int:
            return EMBEDDING_DIM

    fake_model = _FakeModel()
    embeddings_module._load_model.cache_clear()
    monkeypatch.setenv("CODIRA_EMBED_BATCH_SIZE", "7")
    monkeypatch.setattr(embeddings_module, "_load_model", lambda: fake_model)

    vectors = embed_texts(["schema migration", "   ", "docstring audit"])

    assert fake_model.calls == [
        (
            ["schema migration", "docstring audit"],
            7,
            True,
            True,
        )
    ]
    assert vectors[0] == [1.0] * EMBEDDING_DIM
    assert vectors[1] == [0.0] * EMBEDDING_DIM
    assert vectors[2] == [2.0] * EMBEDDING_DIM


def test_embed_texts_uses_repo_default_batch_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Use the repository default batch size when no override is configured.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control embedding model loading.

    Returns
    -------
    None
        The test asserts the default batch size reaches the backend call.
    """

    class _FakeVector:
        def __init__(self, values: list[float]) -> None:
            self._values = values

        def tolist(self) -> list[float]:
            return list(self._values)

    class _FakeModel:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def encode(
            self,
            sentences: list[str],
            *,
            batch_size: int,
            convert_to_numpy: bool,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> list[_FakeVector]:
            del sentences, convert_to_numpy, normalize_embeddings, show_progress_bar
            self.batch_sizes.append(batch_size)
            return [_FakeVector([1.0] * EMBEDDING_DIM)]

        def get_sentence_embedding_dimension(self) -> int:
            return EMBEDDING_DIM

    fake_model = _FakeModel()
    embeddings_module._load_model.cache_clear()
    monkeypatch.delenv("CODIRA_EMBED_BATCH_SIZE", raising=False)
    monkeypatch.setattr(embeddings_module, "_load_model", lambda: fake_model)

    assert embed_texts(["schema migration"]) == [[1.0] * EMBEDDING_DIM]
    assert fake_model.batch_sizes == [DEFAULT_EMBEDDING_BATCH_SIZE]


def test_configure_torch_runtime_uses_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Apply explicit Torch thread overrides when they are configured.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control the imported Torch module.

    Returns
    -------
        None
            The test asserts explicit Torch thread overrides are applied.
    """

    class _FakeTorch:
        def __init__(self) -> None:
            self.num_threads: list[int] = []
            self.num_interop_threads: list[int] = []

        def set_num_threads(self, value: int) -> None:
            self.num_threads.append(value)

        def set_num_interop_threads(self, value: int) -> None:
            self.num_interop_threads.append(value)

    fake_torch = _FakeTorch()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setenv("CODIRA_TORCH_NUM_THREADS", "3")
    monkeypatch.setenv("CODIRA_TORCH_NUM_INTEROP_THREADS", "2")

    embeddings_module._configure_torch_runtime()

    assert fake_torch.num_threads == [3]
    assert fake_torch.num_interop_threads == [2]


def test_flush_embedding_rows_batches_and_reuses_identical_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Batch recomputed rows and reuse same-run vectors for identical payloads.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control the embedding backend.

    Returns
    -------
    None
        The test asserts duplicate payloads are encoded once and inserted twice.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE embeddings (
            id INTEGER PRIMARY KEY,
            object_type TEXT NOT NULL,
            object_id INTEGER NOT NULL,
            backend TEXT NOT NULL,
            version TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL
        )
        """)

    calls: list[list[str]] = []

    def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        calls.append(list(texts))
        return [[float(index + 1)] * EMBEDDING_DIM for index, _text in enumerate(texts)]

    monkeypatch.setattr("codira.indexer.embed_texts", fake_embed_texts)
    backend = embeddings_module.get_embedding_backend()
    rows = [
        PendingEmbeddingRow("symbol", 1, "stable-a", "shared payload"),
        PendingEmbeddingRow("symbol", 2, "stable-b", "shared payload"),
        PendingEmbeddingRow("symbol", 3, "stable-c", "unique payload"),
    ]

    recomputed, reused = _flush_embedding_rows(
        conn,
        embedding_rows=rows,
        backend=backend,
        previous_embeddings={
            "stable-c": StoredEmbeddingRow(
                stable_id="stable-c",
                content_hash="mismatch",
                dim=backend.dim,
                vector=b"",
            )
        },
    )

    stored = conn.execute(
        "SELECT object_id, content_hash, vector FROM embeddings ORDER BY object_id"
    ).fetchall()

    assert recomputed == 3
    assert reused == 0
    assert calls == [["shared payload", "unique payload"]]
    assert len(stored) == 3
    assert stored[0][2] == stored[1][2]
    assert stored[0][2] != stored[2][2]
    conn.close()


def test_index_repo_persists_symbol_embeddings(tmp_path: Path) -> None:
    """
    Ensure indexing stores one deterministic embedding per indexed symbol.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts stored embedding metadata and row counts.
    """
    _write_embedding_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    conn = sqlite3.connect(get_db_path(tmp_path))
    try:
        symbol_count = conn.execute("SELECT COUNT(*) FROM symbol_index").fetchone()[0]
        embedding_rows = conn.execute("""
            SELECT object_type, backend, version, dim
            FROM embeddings
            ORDER BY object_type, object_id
            """).fetchall()
    finally:
        conn.close()

    assert len(embedding_rows) == symbol_count
    assert all(
        row == ("symbol", EMBEDDING_BACKEND, EMBEDDING_VERSION, EMBEDDING_DIM)
        for row in embedding_rows
    )


def test_embedding_candidates_are_deterministic_and_overlap(tmp_path: Path) -> None:
    """
    Ensure similar phrasings produce overlapping embedding-channel results.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts deterministic rankings and overlapping top results.
    """
    _write_embedding_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    first = embedding_candidates(
        tmp_path,
        "schema migration",
        limit=5,
        min_score=0.1,
    )
    second = embedding_candidates(
        tmp_path,
        "migrate schema rules",
        limit=5,
        min_score=0.1,
    )
    repeated = embedding_candidates(
        tmp_path,
        "schema migration",
        limit=5,
        min_score=0.1,
    )

    assert first == repeated
    assert first
    assert second

    first_symbols = {symbol for _score, symbol in first}
    second_symbols = {symbol for _score, symbol in second}
    assert first_symbols & second_symbols


def test_embedding_channel_does_not_regress_exact_symbol_lookup(tmp_path: Path) -> None:
    """
    Ensure exact symbol lookup remains unchanged after embedding indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts exact symbol lookup still returns the target function.
    """
    _write_embedding_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    rows = find_symbol(tmp_path, "validate_schema_rules")
    assert rows == [
        (
            "function",
            "pkg.sample",
            "validate_schema_rules",
            str(tmp_path / "pkg" / "sample.py"),
            3,
        )
    ]


def test_c_embedding_candidates_include_include_context(tmp_path: Path) -> None:
    """
    Include C module comments and include context in semantic retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts embedding retrieval can match C include-context text.
    """
    native = tmp_path / "native"
    native.mkdir()
    (native / "sample.h").write_text(
        "struct Node { int value; };\n",
        encoding="utf-8",
    )
    (native / "sample.c").write_text(
        "/* Vector reduction implementation. */\n"
        '#include "native/sample.h"\n'
        "#include <stdio.h>\n"
        "\n"
        "int public_api(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    results = embedding_candidates(
        tmp_path,
        "vector reduction stdio sample header",
        limit=5,
        min_score=0.1,
    )

    assert results
    symbols = {symbol for _score, symbol in results}
    assert (
        "module",
        "native.sample",
        "native.sample",
        str(tmp_path / "native" / "sample.c"),
        1,
    ) in symbols
    assert (
        "function",
        "native.sample",
        "public_api",
        str(tmp_path / "native" / "sample.c"),
        5,
    ) in symbols


def test_c_embedding_candidates_include_header_source_pairing(tmp_path: Path) -> None:
    """
    Include C header and source pairing context in semantic retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts semantic retrieval can match paired header/source text.
    """
    native = tmp_path / "native"
    native.mkdir()
    (native / "sample.h").write_text(
        "struct Node { int value; };\n",
        encoding="utf-8",
    )
    (native / "sample.c").write_text(
        '#include "native/sample.h"\n'
        "\n"
        "int public_api(void) {\n"
        "    return 1;\n"
        "}\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    header_results = embedding_candidates(
        tmp_path,
        "paired header native sample h",
        limit=5,
        min_score=0.1,
    )
    assert header_results
    header_symbols = {symbol for _score, symbol in header_results}
    assert (
        "function",
        "native.sample",
        "public_api",
        str(tmp_path / "native" / "sample.c"),
        3,
    ) in header_symbols

    source_results = embedding_candidates(
        tmp_path,
        "paired source native sample c",
        limit=5,
        min_score=0.1,
    )
    assert source_results
    source_symbols = {symbol for _score, symbol in source_results}
    assert (
        "struct",
        "native.sample",
        "Node",
        str(tmp_path / "native" / "sample.h"),
        1,
    ) in source_symbols


def test_python_embedding_candidates_include_fixture_assertion_context(
    tmp_path: Path,
) -> None:
    """
    Include Python fixture, setup, and assertion context in semantic retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts embedding retrieval can match Python semantic-unit
        context lines.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        '"""Validation helpers."""\n'
        "\n"
        "import pytest\n"
        "\n"
        "@pytest.fixture\n"
        "def payload_fixture():\n"
        "    return 1\n"
        "\n"
        "def setup_function():\n"
        "    return None\n"
        "\n"
        "def test_payload(payload_fixture):\n"
        '    """Validate payload behavior."""\n'
        "    assert payload_fixture == 1\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    fixture_results = embedding_candidates(
        tmp_path,
        "pytest fixture payload",
        limit=5,
        min_score=0.1,
    )
    assert fixture_results
    fixture_symbols = {symbol for _score, symbol in fixture_results}
    assert (
        "function",
        "tests.test_sample",
        "payload_fixture",
        str(tmp_path / "tests" / "test_sample.py"),
        6,
    ) in fixture_symbols

    setup_results = embedding_candidates(
        tmp_path,
        "setup function validation",
        limit=5,
        min_score=0.1,
    )
    assert setup_results
    setup_symbols = {symbol for _score, symbol in setup_results}
    assert (
        "function",
        "tests.test_sample",
        "setup_function",
        str(tmp_path / "tests" / "test_sample.py"),
        9,
    ) in setup_symbols

    assertion_results = embedding_candidates(
        tmp_path,
        "assertions payload validation",
        limit=5,
        min_score=0.1,
    )
    assert assertion_results
    assertion_symbols = {symbol for _score, symbol in assertion_results}
    assert (
        "function",
        "tests.test_sample",
        "test_payload",
        str(tmp_path / "tests" / "test_sample.py"),
        12,
    ) in assertion_symbols


def test_embeddings_cli_prints_backend_and_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Verify the embedding inspection CLI path.

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
        The test asserts backend metadata and a ranked match line.
    """
    _write_embedding_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "emb", "schema migration rules", "--limit", "2"],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert (
        "backend:"
        f" {EMBEDDING_BACKEND}"
        f" version={EMBEDDING_VERSION}"
        f" dim={EMBEDDING_DIM}"
    ) in captured.out
    assert "pkg.sample.validate_schema_rules" in captured.out


def test_cli_reports_embedding_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Collapse embedding backend failures into concise CLI output.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control CLI dispatch behavior.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts operator-facing stderr output and exit status.
    """
    monkeypatch.setattr(
        "codira.cli._run_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            EmbeddingBackendError("Install codira[semantic].")
        ),
    )
    monkeypatch.setattr(sys, "argv", ["codira", "index"])

    assert main() == 2
    captured = capsys.readouterr()
    assert "[codira] Install codira[semantic]." in captured.err
    assert captured.out == ""


def test_load_model_provisions_missing_local_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Provision the embedding artifact automatically on first load miss.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control model-loading side effects.

    Returns
    -------
    None
        The test asserts provisioning occurs before the final offline retry.
    """

    class _FakeModel:
        def get_sentence_embedding_dimension(self) -> int:
            return EMBEDDING_DIM

    provisioned = False
    calls: list[bool] = []

    def fake_load_sentence_transformer(
        sentence_transformer: type[object],
        *,
        offline: bool,
    ) -> object:
        del sentence_transformer
        calls.append(offline)
        if offline and not provisioned:
            msg = "missing local artifact"
            raise OSError(msg)
        return _FakeModel()

    def fake_provision_embedding_model(*, quiet: bool = False) -> None:
        nonlocal provisioned
        del quiet
        provisioned = True

    embeddings_module._load_model.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=object),
    )
    monkeypatch.setattr(
        embeddings_module,
        "_load_sentence_transformer",
        fake_load_sentence_transformer,
    )
    monkeypatch.setattr(
        embeddings_module,
        "provision_embedding_model",
        fake_provision_embedding_model,
    )

    model = embeddings_module._load_model()

    assert isinstance(model, _FakeModel)
    assert calls == [True, True]
    assert provisioned is True
    embeddings_module._load_model.cache_clear()
