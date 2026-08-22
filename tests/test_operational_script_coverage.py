"""Deterministic coverage tests for repository operational scripts.

The tests exercise local parsing, pagination, filesystem, and subprocess
contracts with controlled collaborators.  They never invoke GitHub, Semgrep,
Codira indexing, or embedding models.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest

from scripts import scriptlib

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script(module_name: str, filename: str) -> ModuleType:
    """Load one standalone script module with its sibling imports available.

    Parameters
    ----------
    module_name : str
        Unique module name used for the dynamic import.
    filename : str
        Script filename below the repository ``scripts`` directory.

    Returns
    -------
    types.ModuleType
        Imported script module.
    """

    script_dir = REPO_ROOT / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, script_dir / filename
        )
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(script_dir))


def _connection(
    nodes: list[dict[str, object]], *, more: bool, cursor: str | None
) -> dict[str, object]:
    """Build a minimal GraphQL connection payload.

    Parameters
    ----------
    nodes : list[dict[str, object]]
        Connection nodes.
    more : bool
        Whether another page follows.
    cursor : str or None
        Cursor for the next page.

    Returns
    -------
    dict[str, object]
        GraphQL connection fixture.
    """

    return {
        "totalCount": len(nodes),
        "pageInfo": {"hasNextPage": more, "endCursor": cursor},
        "nodes": nodes,
    }


def test_snapshot_generator_completes_paginated_issue_and_milestone_connections(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cover snapshot pagination and atomic JSON rendering without GitHub.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to supply deterministic GraphQL pages.
    tmp_path : pathlib.Path
        Temporary output directory.

    Returns
    -------
    None
        The test asserts flattened connections and JSON output.
    """

    helper = _load_script("coverage_snapshot", "generate_github_snapshot.py")
    issue_pages = [
        {
            "data": {
                "repository": {
                    "issues": _connection([{"number": 1}], more=True, cursor="next")
                }
            }
        },
        {
            "data": {
                "repository": {
                    "issues": _connection([{"number": 2}], more=False, cursor=None)
                }
            }
        },
    ]
    monkeypatch.setattr(helper, "_run_graphql", lambda _query: issue_pages.pop(0))
    issues = helper.build_issues_snapshot()
    assert issues["data"]["repository"]["issues"]["nodes"] == [
        {"number": 1},
        {"number": 2},
    ]

    milestone = {
        "number": 7,
        "issues": _connection([{"number": 10}], more=True, cursor="nested"),
    }
    milestone_pages = [
        {
            "data": {
                "repository": {
                    "milestones": _connection([milestone], more=False, cursor=None)
                }
            }
        },
        {
            "data": {
                "repository": {
                    "milestone": {
                        "issues": _connection([{"number": 11}], more=False, cursor=None)
                    }
                }
            }
        },
    ]
    monkeypatch.setattr(helper, "_run_graphql", lambda _query: milestone_pages.pop(0))
    milestones = helper.build_milestones_snapshot()
    assert milestones["data"]["repository"]["milestones"]["nodes"][0]["issues"][
        "nodes"
    ] == [{"number": 10}, {"number": 11}]

    output = tmp_path / "nested" / "issues.json"
    helper.write_snapshot(issues, output)
    assert json.loads(output.read_text(encoding="utf-8")) == issues
    assert helper._after_clause(None) == "null"
    assert helper._after_clause('a"b') == '"a\\"b"'


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "GraphQL response is missing data"),
        ({"data": {}}, "GraphQL response is missing repository"),
        ({"data": {"repository": {}}}, "GraphQL response is missing repository.issues"),
    ],
)
def test_snapshot_generator_rejects_invalid_response_shapes(
    payload: dict[str, object],
    message: str,
) -> None:
    """Cover controlled malformed-GraphQL failure paths.

    Parameters
    ----------
    payload : dict[str, object]
        Malformed response fixture.
    message : str
        Expected controlled error message.

    Returns
    -------
    None
        The test asserts response-shape validation.
    """

    helper = _load_script("coverage_snapshot_shapes", "generate_github_snapshot.py")
    with pytest.raises(helper.SnapshotError, match=message):
        helper._repository_connection(payload, "issues")


def test_snapshot_generator_maps_process_and_json_errors(
    monkeypatch: MonkeyPatch,
) -> None:
    """Cover controlled GitHub CLI error mapping.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the process boundary.

    Returns
    -------
    None
        The test asserts both subprocess and JSON failures become SnapshotError.
    """

    helper = _load_script("coverage_snapshot_process", "generate_github_snapshot.py")

    def fail_process(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        """Raise a subprocess failure carrying stderr."""

        raise subprocess.CalledProcessError(1, ["gh"], stderr="denied")

    monkeypatch.setattr(helper.subprocess, "run", fail_process)
    with pytest.raises(helper.SnapshotError, match="denied"):
        helper._run_graphql("query")

    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["gh"], 0, "not-json"),
    )
    with pytest.raises(helper.SnapshotError, match="invalid JSON"):
        helper._run_graphql("query")


def test_scriptlib_restores_configs_and_wraps_process_helpers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Cover config restoration, process wrappers, and formatting helpers.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace subprocess and executable discovery.
    tmp_path : pathlib.Path
        Temporary repository and backup roots.
    capsys : pytest.CaptureFixture[str]
        Captured tee output.

    Returns
    -------
    None
        The test asserts local helper behavior without starting real commands.
    """

    present = tmp_path / "present"
    absent = tmp_path / "absent"
    config = present / ".codira" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("original\n", encoding="utf-8")
    backup = tmp_path / "backup"
    with scriptlib.RepoConfigRestore([present, absent], backup):
        config.write_text("changed\n", encoding="utf-8")
        (absent / ".codira").mkdir(parents=True)
        (absent / ".codira" / "config.toml").write_text("temporary\n", encoding="utf-8")
    assert config.read_text(encoding="utf-8") == "original\n"
    assert not (absent / ".codira" / "config.toml").exists()

    observed: dict[str, object] = {}
    monkeypatch.setattr(
        "scripts.scriptlib.subprocess.run",
        lambda args, **kwargs: (
            observed.update(args=args, **kwargs) or subprocess.CompletedProcess(args, 3)
        ),
    )
    assert scriptlib.run(["tool", "arg"], cwd=tmp_path, env={"X": "1"}).returncode == 3
    assert observed["cwd"] == str(tmp_path)
    monkeypatch.setattr(
        "scripts.scriptlib.subprocess.check_output", lambda *_args, **_kwargs: "value\n"
    )
    assert scriptlib.output(["tool"]) == "value\n"

    class _FakeProcess:
        """Minimal line-producing process replacement."""

        stdout = iter(["one\n", "two\n"])

        def wait(self) -> int:
            """Return a deterministic child status."""

            return 4

    monkeypatch.setattr(
        "scripts.scriptlib.subprocess.Popen", lambda *_args, **_kwargs: _FakeProcess()
    )
    assert scriptlib.tee_run(["tool"], tmp_path / "log.txt", env={}) == 4
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "one\ntwo\n"
    assert capsys.readouterr().out == "one\ntwo\n"
    assert scriptlib.safe_slug("a/b c") == "a_b_c"
    assert [scriptlib.format_duration(value) for value in (4, 65, 3661)] == [
        "4s",
        "1m 05s",
        "1h 01m 01s",
    ]
    monkeypatch.setattr("scripts.scriptlib.time.time", lambda: 12.9)
    assert scriptlib.epoch_seconds() == 12


def test_scriptlib_resolves_configured_and_missing_executables(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cover executable discovery precedence and its controlled failure.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control environment and PATH discovery.
    tmp_path : pathlib.Path
        Temporary executable paths.

    Returns
    -------
    None
        The test asserts configured paths win and missing tools fail clearly.
    """

    python = tmp_path / "python"
    codira = tmp_path / "codira"
    python.touch()
    codira.touch()
    monkeypatch.setenv("PYTHON", str(python))
    monkeypatch.setenv("CODIRA", str(codira))
    assert scriptlib.resolve_python() == str(python)
    assert scriptlib.resolve_codira() == str(codira)
    monkeypatch.delenv("PYTHON")
    monkeypatch.delenv("CODIRA")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr("scripts.scriptlib.shutil.which", lambda _name: None)
    monkeypatch.setattr("scripts.scriptlib.Path.exists", lambda _path: False)
    with pytest.raises(SystemExit, match="Python executable not found"):
        scriptlib.resolve_python()
    with pytest.raises(SystemExit, match="Codira executable not found"):
        scriptlib.resolve_codira()


def test_semgrep_fixture_runner_reports_success_and_failure(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    """Cover Semgrep fixture result handling without invoking Semgrep.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the subprocess boundary.
    capsys : pytest.CaptureFixture[str]
        Captured validator diagnostics.

    Returns
    -------
    None
        The test asserts expected identifier reporting and aggregate failure.
    """

    helper = _load_script("coverage_semgrep_validator", "validate_semgrep_rules.py")
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [], 0, "rule.one\nrule.two", ""
        ),
    )
    assert helper.run_fixture("sample", "fixtures", ("rule.one", "rule.two")) == 0
    monkeypatch.setattr(
        helper.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, "rule.one", ""),
    )
    assert helper.run_fixture("sample", "fixtures", ("rule.one", "rule.two")) == 1
    monkeypatch.setattr(
        helper, "FIXTURES", (("one", "target", ("one",)), ("two", "target", ("two",)))
    )
    monkeypatch.setattr(helper, "run_fixture", lambda name, *_args: int(name == "two"))
    assert helper.main() == 1
    assert "[FAIL] 1 Semgrep fixture checks failed" in capsys.readouterr().out


def test_benchmark_index_main_instruments_and_restores_dependencies(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Cover benchmark instrumentation with an entirely in-process index pass.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace the indexer, backend, and artifact boundaries.
    tmp_path : pathlib.Path
        Temporary repository root.
    capsys : pytest.CaptureFixture[str]
        Captured benchmark JSON report.

    Returns
    -------
    None
        The test asserts instrumentation records batches and restores hooks.
    """

    helper = _load_script("coverage_benchmark_index", "benchmark_index.py")

    class _Backend:
        """Small rebuild-capable backend fixture."""

        def rebuild_derived_indexes(
            self,
            root: Path,
            *,
            conn: object | None = None,
        ) -> None:
            """Accept the benchmark's wrapped rebuild call."""

            del root, conn

    class _BackendInstance:
        """Backend instance fixture exposing initialization and name."""

        name = "sqlite"

        def initialize(self, root: Path) -> None:
            """Accept initialization for the temporary root."""

            del root

    class _Report:
        """Minimal index report fixture for benchmark JSON rendering."""

        indexed = 2
        reused = 1
        deleted = 0
        failed = 0
        embeddings_recomputed = 2
        embeddings_reused = 1
        coverage_issues: list[object] = []
        failures: list[object] = []
        analysis_concurrency = type(
            "Concurrency",
            (),
            {
                "requested_strategy": "serial",
                "effective_strategy": "serial",
                "workers": 1,
                "reason": "test",
            },
        )()

    support = ModuleType("coverage_backend_support")
    support._flush_embedding_rows = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    support.embed_texts = (  # type: ignore[attr-defined]
        lambda texts, *, root=None: [[float(len(text))] for text in texts]
    )
    args = type(
        "Args",
        (),
        {
            "root": str(tmp_path),
            "output_dir": None,
            "config_file": None,
            "full": True,
            "output": tmp_path / "benchmark.json",
        },
    )()
    monkeypatch.setattr(
        helper,
        "build_parser",
        lambda: type("Parser", (), {"parse_args": lambda self: args})(),
    )
    monkeypatch.setattr(helper, "active_backend_class", lambda _root: _Backend)
    monkeypatch.setattr(helper, "active_backend_support_module", lambda _root: support)
    monkeypatch.setattr(
        helper, "active_index_backend", lambda *, root=None: _BackendInstance()
    )
    monkeypatch.setattr(helper, "benchmark_metadata", lambda _root: {"test": True})
    monkeypatch.setattr(
        helper, "override_repo_config_path", lambda _path: nullcontext()
    )
    monkeypatch.setattr(
        helper,
        "write_json_artifact",
        lambda path, payload: path.write_text(json.dumps(payload), encoding="utf-8"),
    )

    def fake_index(_root: Path, *, full: bool) -> _Report:
        """Exercise every installed benchmark wrapper once."""

        assert full is True
        helper.indexer._collect_project_scan_state()
        helper.indexer._collect_indexed_file_analyses()
        helper.indexer._persist_indexed_file_analyses()
        helper.indexer._select_language_analyzer()
        assert list(helper.indexer.iter_project_files()) == []
        helper.indexer.file_metadata()
        support._flush_embedding_rows()
        _Backend().rebuild_derived_indexes(tmp_path)
        helper.embeddings_module.embed_texts(["same", "same", "other"], root=tmp_path)
        return _Report()

    def pre_main_scan() -> None:
        """Provide a restorable scan collector seam."""

    monkeypatch.setattr(helper.indexer, "_collect_project_scan_state", pre_main_scan)
    monkeypatch.setattr(helper.indexer, "_collect_indexed_file_analyses", lambda: None)
    monkeypatch.setattr(helper.indexer, "_persist_indexed_file_analyses", lambda: None)
    monkeypatch.setattr(helper.indexer, "_select_language_analyzer", lambda: None)
    monkeypatch.setattr(helper.indexer, "iter_project_files", lambda: iter(()))
    monkeypatch.setattr(helper.indexer, "file_metadata", lambda: None)
    monkeypatch.setattr(helper, "index_repo", fake_index)

    assert helper.main() == 0
    payload = json.loads((tmp_path / "benchmark.json").read_text(encoding="utf-8"))
    assert payload["embedding_batches"] == {
        "calls": 1,
        "total_rows": 3,
        "unique_rows": 2,
        "max_batch_size": 3,
        "max_unique_batch_size": 2,
        "avg_batch_size": 3.0,
        "avg_unique_batch_size": 2.0,
        "duplicate_rows": 1,
    }
    assert helper.indexer._collect_project_scan_state is pre_main_scan
    assert '"indexed": 2' in capsys.readouterr().out


def test_embedding_campaign_helpers_cover_local_artifacts(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cover campaign helper parsing, checkpoints, and local run outcomes.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace campaign subprocess execution.
    tmp_path : pathlib.Path
        Temporary manifests and campaign artifacts.

    Returns
    -------
    None
        The test asserts helper output without loading models or repositories.
    """

    helper = _load_script(
        "coverage_embedding_campaign", "run_final_embedding_model_campaign.py"
    )
    manifest = tmp_path / "repos.json"
    manifest.write_text(
        json.dumps(
            {"repositories": [{"label": "repo", "path": str(tmp_path / "repo")}]}
        ),
        encoding="utf-8",
    )
    models = tmp_path / "models.json"
    models.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "large",
                        "engine": "onnx",
                        "model": "m",
                        "version": "1",
                        "dimension": 768,
                        "config": {"max_tokens": "bad"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    repo = helper.read_repositories(manifest)[0]
    model = helper.read_models(models)[0]
    assert helper.safe_embedding_batch_size(model) == 1
    assert helper.safe_max_text_chars(model) == 2000
    assert helper.safe_onnx_threads(model) == (4, 1)
    assert helper.concrete_backends("both") == ("sqlite", "duckdb")
    with pytest.raises(ValueError, match="unknown backend"):
        helper.concrete_backends("memory")
    assert "max_tokens = 512" in helper.render_model_config(model, "duckdb")

    metadata = tmp_path / "metadata"
    matrix = tmp_path / "matrix"
    helper.write_run_metadata(
        metadata_root=metadata,
        manifest_path=manifest,
        model_manifest_path=models,
        baseline_path="",
        backend_mode="sqlite",
        stamp="stamp",
        matrix_root=matrix,
        python="python",
        codira="codira",
        runs=2,
        warmup=0,
    )
    assert "BACKEND_MODE=sqlite" in (metadata / "environment.txt").read_text(
        encoding="utf-8"
    )
    selected = metadata / "one.json"
    helper.write_single_repo_manifest(manifest, repo, selected)
    assert (
        json.loads(selected.read_text(encoding="utf-8"))["repositories"][0]["label"]
        == "repo"
    )

    checkpoints = matrix / "checkpoints"
    checkpoints.mkdir(parents=True)
    labels = checkpoints / "labels.txt"
    index = checkpoints / "index.tsv"
    index.write_text("label\theader\n", encoding="utf-8")
    helper.append_checkpoint(
        index,
        labels,
        label="done",
        model=model,
        backend_mode="sqlite",
        repo=repo,
        status=0,
        log_path=tmp_path / "run.log",
    )
    assert helper.find_checkpoint_root("done", tmp_path) == matrix

    monkeypatch.setattr(helper.subprocess, "call", lambda *_args, **_kwargs: 0)
    config_root = tmp_path / "configs"
    config_root.mkdir()
    log_root = tmp_path / "logs"
    log_root.mkdir()
    status, seen = helper.run_repo_campaign(
        model=model,
        repo=repo,
        backend="sqlite",
        config_root=config_root,
        metadata_root=metadata,
        campaign_root=matrix / "campaigns",
        log_root=log_root,
        stamp="next",
        manifest_path=manifest,
        python="python",
        codira="codira",
        labels_path=labels,
        checkpoint_index=index,
        restart_from="",
        restart_seen=True,
        runs=1,
        warmup=0,
    )
    assert (status, seen) == (0, True)
    assert "ckpt_next_large_sqlite_1-repo" in labels.read_text(encoding="utf-8")
    skipped, restart_seen = helper.run_repo_campaign(
        model=model,
        repo=repo,
        backend="sqlite",
        config_root=config_root,
        metadata_root=metadata,
        campaign_root=matrix / "campaigns",
        log_root=log_root,
        stamp="later",
        manifest_path=manifest,
        python="python",
        codira="codira",
        labels_path=labels,
        checkpoint_index=index,
        restart_from="expected",
        restart_seen=False,
        runs=1,
        warmup=0,
    )
    assert (skipped, restart_seen) == (0, False)


def test_embedding_campaign_main_runs_mocked_full_matrix(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cover campaign orchestration without preflight downloads or model runs.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to replace process execution and campaign phases.
    tmp_path : pathlib.Path
        Temporary manifests and artifact root.

    Returns
    -------
    None
        The test asserts one deterministic matrix run reaches its README.
    """

    helper = _load_script(
        "coverage_embedding_campaign_main", "run_final_embedding_model_campaign.py"
    )
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    manifest = tmp_path / "repos.json"
    manifest.write_text(
        json.dumps({"repositories": [{"label": "repo", "path": str(repo_path)}]}),
        encoding="utf-8",
    )
    models = tmp_path / "models.json"
    models.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": "small",
                        "engine": "onnx",
                        "model": "m",
                        "version": "1",
                        "dimension": 384,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, str]] = []

    def fake_phase(**kwargs: object) -> tuple[int, bool]:
        """Record each model/backend phase without invoking baseline tooling."""

        model = kwargs["model"]
        calls.append((model.id, cast("str", kwargs["backend"])))  # type: ignore[attr-defined]
        return (0, cast("bool", kwargs["restart_seen"]))

    monkeypatch.setattr(helper, "resolve_python", lambda: "python")
    monkeypatch.setattr(helper, "resolve_codira", lambda: "codira")
    monkeypatch.setattr(helper.subprocess, "call", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(helper, "run_repo_campaign", fake_phase)
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("STAMP", "matrix")

    assert (
        helper.main(
            [
                "--manifest",
                str(manifest),
                "--model-manifest",
                str(models),
                "--backend",
                "both",
                "--runs",
                "1",
                "--warmup",
                "0",
            ]
        )
        == 0
    )
    matrix = tmp_path / "artifacts" / "matrix"
    assert calls == [("small", "sqlite"), ("small", "duckdb")]
    assert (matrix / "README.md").exists()
    assert (matrix / "configs" / "small-duckdb.toml").exists()
