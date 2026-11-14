"""Regression tests for deterministic analyzer scheduling."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

import pytest
from codira_analyzer_python import PythonAnalyzer

import codira.indexer as indexer_module
from codira.config import IndexConcurrencyConfig
from codira.contracts import (
    AnalyzerConcurrencyDeclaration,
    LanguageAnalyzer,
)
from codira.indexer import (
    IndexConcurrencyReport,
    _collect_indexed_file_analyses,
    _resolve_index_concurrency,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from codira.models import AnalysisResult


class _ConcurrentAnalyzer:
    """
    Minimal analyzer declaring both isolated worker modes.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances expose only the scheduler contract used by these tests.
    """

    name = "test"
    version = "1"
    discovery_globs = ("*.test",)

    def supports_path(self, path: Path) -> bool:
        """
        Reject every path because scheduler tests do not parse source.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source file.

        Returns
        -------
        bool
            Always ``False``.
        """

        del path
        return False

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Reject parsing because no test task reaches this method.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source file.
        root : pathlib.Path
            Repository root.

        Returns
        -------
        codira.models.AnalysisResult
            This method never returns.

        Raises
        ------
        AssertionError
            Always raised when an unrelated test invokes parsing.
        """

        del path, root
        msg = "scheduler test analyzer must not parse files"
        raise AssertionError(msg)

    def analyzer_concurrency_declaration(self) -> AnalyzerConcurrencyDeclaration:
        """
        Return the isolated-worker contract used by scheduler tests.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerConcurrencyDeclaration
            Explicit process and thread guarantees.
        """

        return AnalyzerConcurrencyDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            supports_process_workers=True,
            supports_thread_workers=True,
            reentrant_after_configure=True,
        )


class _UndeclaredAnalyzer:
    """
    Analyzer fixture intentionally missing a concurrency declaration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The class intentionally omits the optional concurrency method.
    """

    name = "test"
    version = "1"


def test_parallel_analysis_keeps_work_bounded_and_ordered() -> None:
    """Keep outstanding tasks bounded while preserving source order.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The scheduler consumes only a bounded prefix before each result.
    """
    consumed: list[int] = []

    def tasks() -> Iterator[indexer_module._AnalysisTask]:
        """Yield tasks while recording how far the input has been consumed.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Iterator
            Ordered synthetic tasks.
        """
        for ordinal in range(20):
            consumed.append(ordinal)
            yield indexer_module._AnalysisTask(ordinal, str(ordinal), {})

    def analyze(
        task: indexer_module._AnalysisTask,
    ) -> indexer_module._AnalysisTaskResult:
        """Return an empty analysis outcome for a synthetic task.

        Parameters
        ----------
        task : codira.indexer._AnalysisTask
            Task whose ordinal identifies the result.

        Returns
        -------
        codira.indexer._AnalysisTaskResult
            Empty successful scheduling outcome.
        """
        return indexer_module._AnalysisTaskResult(task.ordinal, None, None, ())

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = indexer_module._bounded_analysis_results(
            executor, analyze, tasks(), 2
        )
        assert next(results).ordinal == 0
        assert len(consumed) == 4
        assert next(results).ordinal == 1
        assert len(consumed) == 5
        assert [result.ordinal for result in results] == list(range(2, 20))


def test_auto_concurrency_uses_process_workers_above_threshold() -> None:
    """
    Prefer bounded process workers for a compatible substantial plan.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts automatic resolution uses process scheduling.
    """

    report = _resolve_index_concurrency(
        IndexConcurrencyConfig(strategy="auto", max_workers=2, min_files=16),
        [cast("LanguageAnalyzer", _ConcurrentAnalyzer())],
        16,
    )

    assert report.effective_strategy == "process"
    assert report.workers == 2
    assert report.reason is None


def test_auto_concurrency_stays_serial_below_threshold() -> None:
    """
    Avoid worker startup for small indexing plans.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the stable threshold fallback reason.
    """

    report = _resolve_index_concurrency(
        IndexConcurrencyConfig(strategy="auto", max_workers=0, min_files=16),
        [cast("LanguageAnalyzer", _ConcurrentAnalyzer())],
        15,
    )

    assert report.effective_strategy == "off"
    assert report.workers == 1
    assert report.reason == "below_min_files"


def test_explicit_concurrency_rejects_undeclared_analyzer() -> None:
    """
    Fail closed when a requested scheduler lacks a plugin declaration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts an explicit process request raises a stable error.
    """

    with pytest.raises(ValueError, match="incompatible analyzer: test"):
        _resolve_index_concurrency(
            IndexConcurrencyConfig(strategy="process", max_workers=2, min_files=16),
            [cast("LanguageAnalyzer", _UndeclaredAnalyzer())],
            16,
        )


def test_thread_workers_reuse_parent_configured_analyzers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Avoid per-task analyzer discovery when scheduling threaded analysis.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to reject accidental worker-side plugin discovery.

    Returns
    -------
    None
        The test asserts threaded tasks use the supplied analyzer instances.
    """

    module = tmp_path / "sample.py"
    module.write_text("value = 1\n", encoding="utf-8")
    metadata = {
        str(module): {
            "path": str(module),
            "hash": hashlib.sha256(module.read_bytes()).hexdigest(),
            "mtime": 1.0,
            "size": module.stat().st_size,
        }
    }

    def reject_worker_discovery(*, root: Path) -> list[LanguageAnalyzer]:
        """
        Reject worker-side discovery for this threaded scheduling test.

        Parameters
        ----------
        root : pathlib.Path
            Requested repository root.

        Returns
        -------
        list[codira.contracts.LanguageAnalyzer]
            This helper never returns.

        Raises
        ------
        AssertionError
            Always raised because threaded work must reuse parent analyzers.
        """

        del root
        msg = "thread workers must reuse parent-configured analyzers"
        raise AssertionError(msg)

    monkeypatch.setattr(
        indexer_module, "active_language_analyzers", reject_worker_discovery
    )

    rows, failures, warnings = _collect_indexed_file_analyses(
        tmp_path,
        [str(module)],
        metadata,
        [cast("LanguageAnalyzer", PythonAnalyzer())],
        IndexConcurrencyReport("thread", "thread", 2),
    )

    assert len(rows) == 1
    assert failures == []
    assert warnings == []


def test_process_worker_reuses_initialized_analyzers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Initialize process-worker analyzers once before multiple tasks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to isolate process-worker module state.

    Returns
    -------
    None
        The test asserts repeated worker tasks do not rediscover analyzers.
    """

    module = tmp_path / "sample.py"
    module.write_text("value = 1\n", encoding="utf-8")
    metadata = {
        "path": str(module),
        "hash": hashlib.sha256(module.read_bytes()).hexdigest(),
        "mtime": 1.0,
        "size": module.stat().st_size,
    }
    task = indexer_module._AnalysisTask(0, str(module), metadata)
    discoveries: list[Path] = []

    def discover_once(*, root: Path) -> list[LanguageAnalyzer]:
        """
        Record process-worker analyzer initialization.

        Parameters
        ----------
        root : pathlib.Path
            Requested repository root.

        Returns
        -------
        list[codira.contracts.LanguageAnalyzer]
            One configured Python analyzer.
        """

        discoveries.append(root)
        return [cast("LanguageAnalyzer", PythonAnalyzer())]

    monkeypatch.setattr(indexer_module, "active_language_analyzers", discover_once)
    monkeypatch.setattr(indexer_module, "_PROCESS_ANALYSIS_ROOT", None)
    monkeypatch.setattr(indexer_module, "_PROCESS_WORKER_ANALYZERS", None)

    indexer_module._initialize_process_analysis_worker(tmp_path)
    first = indexer_module._analyze_index_task_in_process_worker(task)
    second = indexer_module._analyze_index_task_in_process_worker(task)

    assert discoveries == [tmp_path]
    assert first.failure is None
    assert second.failure is None
