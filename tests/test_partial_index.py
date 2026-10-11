"""Regression coverage for usable partial publications.

Parameters
----------
None

Returns
-------
None
    Failed source never causes perpetual indexing or complete-coverage claims.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

import codira.indexer as indexer_module
from codira.cli import main
from codira.cli_index import _ensure_index
from codira.index_coverage import index_coverage
from codira.index_generation import IndexGenerationStore
from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.registry import active_index_backend
from codira.storage import get_metadata_path

if TYPE_CHECKING:
    from codira.models import AnalysisResult


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
@pytest.mark.parametrize("full", [False, True])
def test_partial_queries_retry_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    backend: str,
    full: bool,
) -> None:
    """Reuse failure snapshots and recover when the source is corrected.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and configuration root.
    monkeypatch : pytest.MonkeyPatch
        Environment and CLI argument isolation.
    capsys : pytest.CaptureFixture[str]
        CLI output capture.
    backend : str
        Structural backend under test.
    full : bool
        Incremental or backend-native full indexing contract.

    Returns
    -------
    None
        Queries, retry and recovery assertions complete.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text(f'[embeddings]\nenabled = false\n[backend]\nname = "{backend}"\n')
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    valid = tmp_path / "valid.py"
    valid.write_text("def answer():\n    return 42\n")
    malformed = tmp_path / "broken.py"
    malformed.write_text("print 'legacy Python syntax'\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "valid.py", "broken.py"], check=True
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    malformed.write_text(malformed.read_text() + "\n")
    active_index_backend(root=tmp_path).initialize(tmp_path)
    analyze = Mock(wraps=indexer_module._collect_indexed_file_analyses)
    monkeypatch.setattr(indexer_module, "_collect_indexed_file_analyses", analyze)
    report = index_repo(tmp_path, full=full)
    assert report.publication_ready
    assert report.indexed == report.failed == 1
    initial = IndexGenerationStore(tmp_path).read()
    assert initial is not None
    assert initial.attempted_file_count == 2
    assert initial.failed_files and initial.failed_files[0]["path"] == "broken.py"
    for _ in range(2):
        monkeypatch.setattr(
            sys, "argv", ["codira", "sym", "answer", "--json", "--path", str(tmp_path)]
        )
        assert main() == 0
        captured = capsys.readouterr()
        assert "Partial index" in captured.err
        assert json.loads(captured.out)["index_coverage"]["complete"] is False
        assert IndexGenerationStore(tmp_path).read() == initial
        assert analyze.call_count == 1
    envelope = MCPAdapter(tmp_path).symbol("answer")
    provenance = cast("dict[str, object]", envelope["provenance"])
    assert cast("dict[str, object]", provenance["index_coverage"])["partial"] is True
    status = cast("dict[str, object]", MCPAdapter(tmp_path).index_status()["result"])
    assert cast("dict[str, object]", status["coverage"])["status"] == "incomplete"
    result = cast("dict[str, object]", envelope["result"])
    symbols = cast("list[dict[str, object]]", result["symbols"])
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "evidence", str(symbols[0]["identity"]), "--path", str(tmp_path)],
    )
    assert main() == 0
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["index_coverage"]["complete"] is False
    for response in (
        MCPAdapter(tmp_path).references("answer"),
        MCPAdapter(tmp_path).impact_analysis("answer"),
    ):
        origin = cast("dict[str, object]", response["provenance"])
        assert cast("dict[str, object]", origin["index_coverage"])["complete"] is False
    retry = index_repo(tmp_path)
    assert retry.failed == 1 and retry.reused == 1
    retried = IndexGenerationStore(tmp_path).read()
    assert retried is not None and retried.generation > initial.generation
    assert analyze.call_count == 2
    valid.write_text("def answer():\n    return 43\n")
    retained = index_repo(tmp_path, retry_failed_files=False)
    assert retained.indexed == 1 and retained.failed == 1
    assert retained.failures[0].reason == report.failures[0].reason
    assert str(malformed) not in analyze.call_args.args[1]
    config.write_text(
        config.read_text() + '[index.coverage]\nexclude_suffixes = [".txt"]\n'
    )
    _ensure_index(tmp_path)
    assert str(malformed) in analyze.call_args.args[1]
    malformed.write_text("def recovered():\n    return 1\n")
    _ensure_index(tmp_path)
    assert index_coverage(tmp_path)["complete"] is True
    recovered = cast(
        "dict[str, object]", MCPAdapter(tmp_path).symbol("recovered")["result"]
    )
    assert recovered["symbols"]


def test_unusable_and_corrupt_publications_are_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject empty or corrupt publications instead of returning partial data.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository.
    monkeypatch : pytest.MonkeyPatch
        Effective configuration override.

    Returns
    -------
    None
        Fatal read contracts are checked for both interfaces.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text("[embeddings]\nenabled = false\n")
    monkeypatch.setenv("CODIRA_CONFIG_FILE", str(config))
    (tmp_path / "broken.py").write_text("print 'broken'\n")
    active_index_backend(root=tmp_path).initialize(tmp_path)
    assert index_repo(tmp_path).failed == 1
    with pytest.raises(SystemExit):
        _ensure_index(tmp_path)
    with pytest.raises(ValueError, match="unavailable"):
        MCPAdapter(tmp_path).symbol("answer")
    (tmp_path / "valid.py").write_text("def answer():\n    return 1\n")
    index_repo(tmp_path)
    metadata_path = get_metadata_path(tmp_path)
    metadata = json.loads(metadata_path.read_text())
    metadata.pop("indexed_file_count")
    metadata_path.write_text(json.dumps(metadata))
    assert index_coverage(tmp_path)["usable"] is True
    assert MCPAdapter(tmp_path).symbol("answer")["result"]
    IndexGenerationStore(tmp_path).path.write_text("{broken")
    assert index_coverage(tmp_path)["usable"] is False
    with pytest.raises(SystemExit):
        _ensure_index(tmp_path)
    with pytest.raises(ValueError, match="corrupt"):
        MCPAdapter(tmp_path).symbol("answer")


@pytest.mark.parametrize("exclude", [False, True])
def test_removed_failure_clears_partial_generation(
    tmp_path: Path, exclude: bool
) -> None:
    """Retire failure snapshots when the operator removes the selected source.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index state.
    exclude : bool
        Remove the failed file or explicitly exclude it from analysis.

    Returns
    -------
    None
        Repeated reads retain the corrected complete generation.
    """
    (tmp_path / ".codira").mkdir()
    config = tmp_path / ".codira/config.toml"
    config.write_text("[embeddings]\nenabled = false\n")
    (tmp_path / "valid.py").write_text("def answer():\n    return 1\n")
    broken = tmp_path / "broken.py"
    broken.write_text("print 'legacy'\n")
    active_index_backend(root=tmp_path).initialize(tmp_path)
    assert index_repo(tmp_path).failed == 1
    if exclude:
        config.write_text(
            config.read_text()
            + '[plugins.analyzer-python]\nexclude_paths = ["broken.py"]\n'
        )
    else:
        broken.unlink()
    _ensure_index(tmp_path)
    ready = IndexGenerationStore(tmp_path).read()
    assert ready is not None and not ready.partial and ready.failed_file_count == 0
    _ensure_index(tmp_path)
    assert IndexGenerationStore(tmp_path).read() == ready


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_artifact_validation_failure_keeps_full_index_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_name: str
) -> None:
    """Publish valid files when another full-index file has duplicate identifiers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and index state.
    monkeypatch : pytest.MonkeyPatch
        Injects deterministic duplicate-artifact validation.
    backend_name : str
        Regular or native bulk persistence backend.

    Returns
    -------
    None
        Generation and backend coverage both disclose the omitted file.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        f'[backend]\nname = "{backend_name}"\n[embeddings]\nenabled = false\n'
    )
    (tmp_path / "bad.py").write_text("def duplicate():\n    return 1\n")
    (tmp_path / "good.py").write_text("def answer():\n    return 1\n")
    backend = active_index_backend(root=tmp_path)
    backend.initialize(tmp_path)
    monkeypatch.setattr(
        indexer_module,
        "_duplicate_analysis_stable_ids",
        Mock(side_effect=[["duplicate"], []]),
    )
    report = index_repo(tmp_path, full=True)
    assert report.failed == report.indexed == 1
    assert report.publication_ready
    assert index_coverage(tmp_path)["usable"] is True
    inventory = backend.load_runtime_inventory(tmp_path)
    assert inventory is not None and not inventory[2]
    assert MCPAdapter(tmp_path).symbol("answer")["result"]


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_deep_valid_python_indexes(tmp_path: Path, backend: str) -> None:
    """Index an assignment deeper than the recursive normalization limit.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and state root.
    backend : str
        Structural backend receiving real Python analysis artifacts.

    Returns
    -------
    None
        Both deep source and an ordinary callable are published successfully.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        f'[embeddings]\nenabled = false\n[backend]\nname = "{backend}"\n'
    )
    (tmp_path / "deep.py").write_text(
        " = ".join(f"a{i}" for i in range(801)) + " = None\n"
    )
    (tmp_path / "good.py").write_text("def answer():\n    return 42\n")
    report = index_repo(tmp_path)
    assert report.indexed == 2 and report.failed == 0
    generation = IndexGenerationStore(tmp_path).read()
    assert generation is not None and generation.state == "ready"
    assert MCPAdapter(tmp_path).symbol("answer")["result"]


def test_source_recursion_failure_retains_other_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain a path-specific traversal failure without aborting publication.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated valid sources and structural configuration.
    monkeypatch : pytest.MonkeyPatch
        Injects a traversal failure into one real analyzer invocation.

    Returns
    -------
    None
        The successful file remains queryable and the failed path is retained.
    """
    from codira_analyzer_python import PythonAnalyzer

    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text("[embeddings]\nenabled = false\n")
    (tmp_path / "bad.py").write_text("x = 1\n")
    (tmp_path / "good.py").write_text("def answer():\n    return 42\n")
    original = PythonAnalyzer.analyze_file

    def analyze(self: PythonAnalyzer, path: Path, root: Path) -> AnalysisResult:
        """Inject the source failure while retaining real analysis elsewhere.

        Parameters
        ----------
        self : PythonAnalyzer
            Active analyzer instance.
        path, root : pathlib.Path
            Selected source and repository root.

        Returns
        -------
        codira.models.AnalysisResult
            Original analysis for the unaffected source.
        """
        if path.name == "bad.py":
            message = "source traversal limit"
            raise RecursionError(message)
        return original(self, path, root)

    monkeypatch.setattr(PythonAnalyzer, "analyze_file", analyze)
    report = index_repo(tmp_path)
    assert report.indexed == report.failed == 1
    assert report.failures[0].error_type == "RecursionError"
    assert Path(report.failures[0].path).name == "bad.py"
    assert index_coverage(tmp_path)["usable"] is True
    assert MCPAdapter(tmp_path).symbol("answer")["result"]


@pytest.mark.parametrize(
    "failure_point", ["_index_repo_unlocked", "_write_metadata_file"]
)
def test_fatal_indexing_finalizes_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    """Finalize unexpected analysis or publication failures and keep history.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Source and index root with a previously successful generation.
    monkeypatch : pytest.MonkeyPatch
        Injects a fatal error outside recoverable per-file analysis.
    failure_point : str
        Analysis or publication operation that fails.

    Returns
    -------
    None
        The error propagates and the generation is failed rather than updating.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text("[embeddings]\nenabled = false\n")
    (tmp_path / "good.py").write_text("def answer():\n    return 42\n")
    index_repo(tmp_path)
    previous = IndexGenerationStore(tmp_path).read()
    assert previous is not None
    monkeypatch.setattr(
        indexer_module, failure_point, Mock(side_effect=RuntimeError("fatal backend"))
    )
    with pytest.raises(RuntimeError, match="fatal backend"):
        index_repo(tmp_path)
    failed = IndexGenerationStore(tmp_path).read()
    assert failed is not None and failed.state == "failed"
    assert failed.generation == previous.generation + 1
    assert failed.last_successful_generation == previous.last_successful_generation
    assert index_coverage(tmp_path)["usable"] is False
