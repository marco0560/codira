"""Regression tests for source-derived labels and resumable automatic scoring.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import (
    build_known_target_dataset as dataset,
    run_known_target_quality as runner,
    run_retrieval_quality_benchmark as legacy,
)
from scripts.known_target_quality import (
    INTENTS,
    Case,
    Target,
    canonical_json,
    case_payload,
    digest_bytes,
    load_cases,
    ranked_locations,
    score_ranking,
)

SOURCE = b'''"""Coordinate the repository indexing pipeline."""
def parse_config():
    """Validate configured indexing options."""
    message = "invalid configured indexing options"
    raise ValueError(message)
'''


def fixture_repository(tmp_path: Path) -> Path:
    """Create a real pinned Git tree for provenance checks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated test directory.

    Returns
    -------
    pathlib.Path
        Repository root.
    """
    root = tmp_path / "source"
    (root / "src").mkdir(parents=True)
    (root / "src/app.py").write_bytes(SOURCE)
    (root / "docs").mkdir()
    (root / "docs/usage.md").write_text(
        "# Configure indexing\n\nUse configuration options.\n"
    )
    git = shutil.which("git") or "/usr/bin/git"
    for command in (
        [git, "init", str(root)],
        [git, "-C", str(root), "add", "."],
        [
            git,
            "-C",
            str(root),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "fixture",
        ],
    ):
        subprocess.run(command, check=True, capture_output=True)
    return root


def fixture_controls(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Generate a tiny balanced case bank with explicit model controls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture directory.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, pathlib.Path]
        Repository manifest, dataset and model manifest.
    """
    root = fixture_repository(tmp_path)
    manifest = tmp_path / "repos.json"
    manifest.write_text(
        canonical_json({"repositories": [{"label": "demo", "path": str(root)}]})
    )
    cases = tmp_path / "cases.jsonl"
    assert dataset.build_dataset(manifest, cases, 1) == 5
    models = tmp_path / "models.json"
    models.write_text(
        canonical_json(
            {
                "models": [
                    {
                        "id": "demo-model",
                        "engine": "onnx",
                        "model": "fixture",
                        "version": "1",
                        "dimension": 384,
                        "config": {},
                    }
                ]
            }
        )
    )
    return manifest, cases, models


def test_generator_is_source_derived_balanced_and_reproducible(tmp_path: Path) -> None:
    """Verify all five categories, pinned source and deterministic regeneration.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.

    Returns
    -------
    None
    """
    manifest, path, _models = fixture_controls(tmp_path)
    cases = load_cases(path)
    assert {case.intent for case in cases} == set(INTENTS)
    assert all(len(case.commit) == 40 for case in cases)
    second = tmp_path / "second.jsonl"
    dataset.build_dataset(manifest, second, 1)
    assert second.read_bytes() == path.read_bytes()
    with pytest.raises(FileExistsError):
        dataset.build_dataset(manifest, path, 1)
    with pytest.raises(ValueError, match="verified"):
        dataset.build_dataset(manifest, tmp_path / "too-large.jsonl", 5)
    changed_query = replace(cases[0], query="Unsupported inferred relevance")
    with pytest.raises(ValueError, match="source-verifiable"):
        runner.validate_sources((changed_query,), {"demo": tmp_path / "source"})


def test_error_messages_exclude_interpolation_and_nested_ownership() -> None:
    """Require literal witnesses and attribute nested raises to their owner.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source = b"""def outer():
    def inner():
        raise ValueError("literal inner error message")
    msg = f"unknown runtime {value}"
    raise ValueError(msg)
"""
    cases = dataset.source_cases("demo", "a" * 40, "src/app.py", source)
    errors = [case for case in cases if case.intent == "error_or_trace_lookup"]
    assert len(errors) == 1
    assert errors[0].targets[0].line == 2
    assert errors[0].query == "literal inner error message"


@pytest.mark.parametrize(
    "change",
    [
        {"intent": "unknown"},
        {"commit": "HEAD"},
        {"query": " "},
        {"targets": []},
        {"targets": [{"path": "../escape.py", "line": 1, "kind": "symbol"}]},
        {"targets": [{"path": "src/app.py", "line": True, "kind": "symbol"}]},
        {"evidence": {"rule": "unknown", "source_sha256": "bad"}},
    ],
)
def test_dataset_rejects_invalid_controls(
    tmp_path: Path, change: dict[str, object]
) -> None:
    """Reject malformed labels rather than silently scoring them.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace.
    change : dict[str, object]
        Invalid replacement fields.

    Returns
    -------
    None
    """
    _manifest, path, _models = fixture_controls(tmp_path)
    row = case_payload(load_cases(path)[0])
    path.write_text(canonical_json({**row, **change}) + "\n")
    with pytest.raises(ValueError):
        load_cases(path)


def test_duplicate_cases_and_empty_dataset_are_rejected(tmp_path: Path) -> None:
    """Keep case denominators and identities unambiguous.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace.

    Returns
    -------
    None
    """
    _manifest, path, _models = fixture_controls(tmp_path)
    line = path.read_text().splitlines()[0]
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="Duplicate case"):
        load_cases(path)
    path.write_text("")
    with pytest.raises(ValueError, match="no cases"):
        load_cases(path)


def test_ranking_scores_exact_locations_without_duplicate_credit() -> None:
    """Require the correct definition and preserve rank-sensitive misses.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    target = Target("src/app.py", 2, "symbol")
    case = Case(
        "one",
        "demo",
        "a" * 40,
        "symbol_lookup",
        "parse_config",
        "emb",
        (target, Target("src/other.py", 5, "symbol")),
        {},
    )
    ranking = (Target("src/app.py", 7, "symbol"), target, target)
    assert score_ranking(case, ranking, 1) == {"hit": 0.0, "recall": 0.0, "mrr": 0.0}
    assert score_ranking(case, ranking, 5) == {"hit": 1.0, "recall": 0.5, "mrr": 0.5}
    assert score_ranking(case, (), 10)["recall"] == 0.0
    with pytest.raises(ValueError, match="positive"):
        score_ranking(case, ranking, 0)


def test_ranked_locations_do_not_promote_nested_evidence(tmp_path: Path) -> None:
    """Respect returned ranks and reject cross-repository paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Repository root.

    Returns
    -------
    None
    """
    payload: dict[str, object] = {
        "status": "ok",
        "command": "emb",
        "results": [
            {
                "file": str(tmp_path / "src/app.py"),
                "lineno": 2,
                "references": [{"file": "src/other.py", "lineno": 5}],
            },
        ],
    }
    assert ranked_locations(payload, tmp_path) == (Target("src/app.py", 2, "symbol"),)
    payload["results"] = [{"file": "/outside/source.py", "lineno": 2}]
    with pytest.raises(ValueError, match="outside"):
        ranked_locations(payload, tmp_path)
    with pytest.raises(ValueError, match="response"):
        ranked_locations({}, tmp_path)


def fake_codira(tmp_path: Path) -> Path:
    """Create a subprocess protocol fixture, without simulating model quality.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test directory.

    Returns
    -------
    pathlib.Path
        Executable fixture path.
    """
    executable = tmp_path / "codira-fixture"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json, sys, sqlite3
from pathlib import Path
args = sys.argv[1:]
command = args[0]
if command == "caps":
    print(json.dumps({"fixture_runtime": "1"}))
elif command == "index":
    state = Path(args[args.index("--output-dir") + 1])
    state.mkdir(parents=True, exist_ok=True)
    (state / "fixture-index").write_text("ready")
    (state / ".codira").mkdir(exist_ok=True)
    with sqlite3.connect(state / ".codira/index.db") as db:
        db.executescript("CREATE TABLE IF NOT EXISTS embeddings(object_type,object_id,content_hash); CREATE TABLE IF NOT EXISTS symbol_index(id,stable_id); CREATE TABLE IF NOT EXISTS documentation_artifacts(id,stable_id);")
        db.execute("DELETE FROM embeddings")
        db.execute("DELETE FROM symbol_index")
        db.execute("DELETE FROM documentation_artifacts")
        db.execute("INSERT INTO embeddings VALUES('symbol',1,'hash-one')")
        db.execute("INSERT INTO symbol_index VALUES(1,'symbol:one')")
    with sqlite3.connect(state / ".codira/embeddings.db") as db:
        db.executescript("CREATE TABLE IF NOT EXISTS vector_sets(id); CREATE TABLE IF NOT EXISTS vector_bindings(object_type,stable_id,content_hash); CREATE TABLE IF NOT EXISTS vector_payloads(content_hash);")
        db.execute("DELETE FROM vector_sets")
        db.execute("DELETE FROM vector_bindings")
        db.execute("DELETE FROM vector_payloads")
        db.execute("INSERT INTO vector_sets VALUES(1)")
        db.execute("INSERT INTO vector_bindings VALUES('symbol','symbol:one','hash-one')")
        db.execute("INSERT INTO vector_payloads VALUES('hash-one')")
    print(json.dumps({"command": "index", "status": "ok", "summary": {"failed": 0, "indexed": 2, "reused": 0, "embedding_complete": True, "embeddings_pending": 0}}))
else:
    root = Path(args[args.index("--path") + 1])
    path, line = ("docs/usage.md", 1) if command == "docs" else ("src/app.py", 2)
    rows = [{"file": str(root / path), "lineno": line}]
    payload = {"contract_version": "2.0.0", "result": {"status": "ok", "items": rows}} if command == "ctx" else {"command": command, "status": "ok", "results": rows}
    print(json.dumps(payload))
"""
    )
    executable.chmod(0o700)
    return executable


def test_campaign_resumes_rescores_and_rejects_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise real subprocesses, source freezing and successful skip behavior.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.
    monkeypatch : pytest.MonkeyPatch
        Host executable substitution.
    capsys : pytest.CaptureFixture[str]
        Captured terminal progress and result output.

    Returns
    -------
    None
    """
    manifest, cases, models = fixture_controls(tmp_path)
    executable = fake_codira(tmp_path)
    monkeypatch.setattr(runner, "resolve_codira", lambda: str(executable))
    output = tmp_path / "run"
    argv = [
        "--dataset",
        str(cases),
        "--repo-manifest",
        str(manifest),
        "--model-manifest",
        str(models),
        "--output",
        str(output),
    ]
    assert legacy.main(["--known-target", *argv]) == 0
    progress = capsys.readouterr().err
    assert "11/11" in progress and "100.0%" in progress
    assert "demo-model/demo | indexing" in progress
    assert "literal" not in progress
    attempts = sorted(output.rglob("measurement.json"))
    assert len(attempts) == 11
    before = {path: path.read_bytes() for path in attempts}
    assert runner.main([*argv, "--resume"]) == 0
    assert "reused 11" in capsys.readouterr().err
    assert runner.main([*argv, "--resume", "--quiet-progress"]) == 0
    assert capsys.readouterr().err == ""
    assert before == {
        path: path.read_bytes() for path in output.rglob("measurement.json")
    }
    report = output / "quality-summary.json"
    first = report.read_bytes()
    assert runner.main(["--output", str(output), "--rescore"]) == 0
    assert report.read_bytes() == first
    summary = json.loads(first)
    result = summary["models"]["demo-model"]
    assert result["failures"] == 0
    assert result["macro"]["1"]["hit"] == 1.0
    assert {"repo:demo", *[f"intent:{intent}" for intent in INTENTS]} == set(
        result["groups"]
    )
    with pytest.raises(ValueError, match="differ"):
        runner.main([*argv, "--resume", "--k", "20"])
    frozen = output / "repositories/demo/src/app.py"
    frozen.write_text("modified")
    with pytest.raises(ValueError, match="modified"):
        runner.main([*argv, "--resume"])


def test_failed_attempts_are_retained_and_success_evidence_is_checked(
    tmp_path: Path,
) -> None:
    """Keep retry evidence and reject modification of saved successful outputs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.

    Returns
    -------
    None
    """
    command = [sys.executable, "-c", "raise SystemExit(7)"]
    operation = tmp_path / "operation"
    assert runner.execute_operation(command, tmp_path, operation, 5)["exit_code"] == 7
    assert runner.execute_operation(command, tmp_path, operation, 5)["exit_code"] == 7
    assert len(tuple(operation.glob("attempt-*"))) == 2
    success = runner.execute_operation(
        [sys.executable, "-c", "print('hello')"], tmp_path, tmp_path / "success", 5
    )
    (Path(str(success["evidence"])) / "stdout").write_text("tampered")
    with pytest.raises(ValueError, match="evidence drift"):
        runner.execute_operation(
            [sys.executable, "-c", "print('hello')"], tmp_path, tmp_path / "success", 5
        )


def test_inventory_rejects_missing_bindings_and_payloads(tmp_path: Path) -> None:
    """Reject indexes that claim success but cannot search their stored rows.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated protocol fixture state.

    Returns
    -------
    None
    """
    executable = fake_codira(tmp_path)
    state = tmp_path / "state"
    subprocess.run(
        [str(executable), "index", "--output-dir", str(state)],
        check=True,
        capture_output=True,
    )
    assert runner.validate_index_inventory(state) == {
        "expected_bindings": 1,
        "searchable_bindings": 1,
    }
    with sqlite3.connect(state / ".codira/embeddings.db") as db:
        db.execute("DELETE FROM vector_bindings")
    with pytest.raises(ValueError, match="Incomplete searchable"):
        runner.validate_index_inventory(state)
    with sqlite3.connect(state / ".codira/embeddings.db") as db:
        db.execute(
            "INSERT INTO vector_bindings VALUES('symbol','symbol:one','hash-one')"
        )
        db.execute("DELETE FROM vector_payloads")
    with pytest.raises(ValueError, match="Incomplete searchable"):
        runner.validate_index_inventory(state)


def test_progress_heartbeat_uses_stderr_and_throttles_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Show bounded-frequency heartbeats while an indexing operation runs.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Clock substitution for deterministic refresh checks.
    capsys : pytest.CaptureFixture[str]
        Captured progress stream.

    Returns
    -------
    None
    """
    progress = runner.RunProgress(2, started=0, active="model/repository | indexing")
    monkeypatch.setattr("scripts.run_known_target_quality.time.monotonic", lambda: 20.0)
    progress.render()
    first = capsys.readouterr()
    assert "0/2" in first.err and "elapsed 20s" in first.err
    assert first.out == ""
    progress.render()
    assert capsys.readouterr().err == ""
    monkeypatch.setattr("scripts.run_known_target_quality.time.monotonic", lambda: 36.0)
    progress.render()
    assert "elapsed 36s" in capsys.readouterr().err
    progress.advance(reused=True)
    assert "50.0% 1/2" in capsys.readouterr().err


def test_macro_and_micro_are_distinct_and_include_missing_slots(tmp_path: Path) -> None:
    """Weight repositories equally for macro scores and every query for micro.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace.

    Returns
    -------
    None
    """
    target = Target("src/app.py", 2, "symbol")
    cases = [
        Case(
            str(index),
            repo,
            "a" * 40,
            "symbol_lookup",
            "parse",
            "emb",
            (target,),
            {"rule": "python_definition", "source_sha256": "b" * 64},
        )
        for index, repo in enumerate(("small", "large", "large"))
    ]
    path = tmp_path / "cases.jsonl"
    path.write_text(
        "".join(canonical_json(case_payload(case)) + "\n" for case in cases)
    )
    runner.write_json(
        tmp_path / "campaign.json",
        {
            "dataset_sha256": digest_bytes(path.read_bytes()),
            "cutoffs": [1, 5, 10],
            "configs": {"model": "config"},
        },
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    stdout = canonical_json(
        {
            "command": "emb",
            "status": "ok",
            "results": [{"file": "src/app.py", "lineno": 2}],
        }
    )
    (evidence / "stdout").write_text(stdout)
    (evidence / "stderr").write_text("")
    runner.write_json(
        tmp_path / "operations/model/small/0/ranking.json",
        {
            "ranking": [{"path": "src/app.py", "line": 2, "kind": "symbol"}],
            "error": None,
            "elapsed_seconds": 0.1,
            "exit_code": 0,
            "timed_out": False,
            "evidence": str(evidence),
            "stdout_sha256": digest_bytes(stdout.encode()),
            "stderr_sha256": digest_bytes(b""),
        },
    )
    result = runner.summarize_run(tmp_path)["models"]
    assert isinstance(result, dict)
    assert result["model"]["macro"]["1"]["hit"] == 0.5
    assert result["model"]["micro"]["1"]["hit"] == pytest.approx(1 / 3)
    assert result["model"]["failures"] == 2


def test_timeout_returns_terminal_measurement(tmp_path: Path) -> None:
    """Retain stdout and a timeout result when terminating a sleeping child.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.

    Returns
    -------
    None
    """
    result = runner.measure(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tmp_path,
        tmp_path / "timeout",
        0.05,
    )
    assert result["timed_out"] is True
    assert result["exit_code"] != 0
    assert (tmp_path / "timeout/measurement.json").is_file()


def test_two_models_use_matched_controls_and_keep_no_gain_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare two fixture models without claiming real model effectiveness.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.
    monkeypatch : pytest.MonkeyPatch
        Fixture executable substitution.

    Returns
    -------
    None
    """
    manifest, cases, models = fixture_controls(tmp_path)
    payload = json.loads(models.read_text())
    payload["models"].append({**payload["models"][0], "id": "second-model"})
    models.write_text(canonical_json(payload))
    executable = fake_codira(tmp_path)
    monkeypatch.setattr(runner, "resolve_codira", lambda: str(executable))
    output = tmp_path / "paired-run"
    assert (
        runner.main(
            [
                "--dataset",
                str(cases),
                "--repo-manifest",
                str(manifest),
                "--model-manifest",
                str(models),
                "--output",
                str(output),
                "--baseline",
                "demo-model",
            ]
        )
        == 0
    )
    summary = json.loads((output / "quality-summary.json").read_text())
    reference = summary["models"]["demo-model"]
    candidate = summary["models"]["second-model"]
    assert reference["macro"] == candidate["macro"]
    assert candidate["decision"] == "rejected"
    assert candidate["comparison"]["macro_recall_at_5_delta"] == 0.0
    assert candidate["comparison"]["material_known_target_gain"] is False
    assert candidate["cost_gates"]["hard_peak_memory_compliance"].startswith(
        "unverified"
    )


def test_raw_evidence_controls_rescoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject changes to either a derived ranking or its retained raw output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Test workspace.
    monkeypatch : pytest.MonkeyPatch
        Fixture executable substitution.

    Returns
    -------
    None
    """
    manifest, cases, models = fixture_controls(tmp_path)
    executable = fake_codira(tmp_path)
    monkeypatch.setattr(runner, "resolve_codira", lambda: str(executable))
    output = tmp_path / "run"
    assert (
        runner.main(
            [
                "--dataset",
                str(cases),
                "--repo-manifest",
                str(manifest),
                "--model-manifest",
                str(models),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    ranking_file = next(output.rglob("ranking.json"))
    original = ranking_file.read_bytes()
    row = json.loads(original)
    row["ranking"] = []
    runner.write_json(ranking_file, row)
    with pytest.raises(ValueError, match="raw evidence"):
        runner.summarize_run(output)
    ranking_file.write_bytes(original)
    stdout = Path(row["evidence"]) / "stdout"
    stdout.write_text("modified response")
    with pytest.raises(ValueError, match="evidence drift"):
        runner.summarize_run(output)


def test_campaign_lock_rejects_concurrent_mutation(tmp_path: Path) -> None:
    """Prevent execution and rescoring from racing on one identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace.

    Returns
    -------
    None
    """
    with (
        runner.campaign_lock(tmp_path / "run"),
        pytest.raises(BlockingIOError),
        runner.campaign_lock(tmp_path / "run"),
    ):
        pytest.fail("A concurrent writer acquired the campaign lock")


def test_public_case_bank_is_balanced_and_pinned() -> None:
    """Validate every distributed public case against its fixture revision.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    root = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/retrieval-quality/known-target-v1"
    )
    cases = load_cases(root / "cases.jsonl")
    fixtures = json.loads((root / "fixtures.json").read_text())
    commits = {row["label"]: row["commit"] for row in fixtures["repositories"]}
    assert len(cases) == 75
    assert {case.repo for case in cases} == set(commits)
    for repo, commit in commits.items():
        for intent in INTENTS:
            cell = [
                case for case in cases if case.repo == repo and case.intent == intent
            ]
            assert len(cell) == 5
            assert all(case.commit == commit for case in cell)


def test_markdown_fences_preserve_heading_ground_truth() -> None:
    """Exclude heading-like text inside mismatched and shorter code fences.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source = b"# Real heading\n````python\n~~~\n# Hidden heading\n```\n# Still hidden\n````\n# Final heading\n"
    assert dataset.markdown_headings(source) == (
        (1, "Real heading"),
        (8, "Final heading"),
    )


def test_rendered_configs_use_current_schema_and_identical_text_limits(
    tmp_path: Path,
) -> None:
    """Guard the configuration defects caught by real runtime qualification.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Fixture workspace.

    Returns
    -------
    None
    """
    import tomllib

    from codira.config import CONFIG_VERSION
    from scripts.run_final_embedding_model_campaign import read_models

    _manifest, _cases, models = fixture_controls(tmp_path)
    model = read_models(models)[0]
    for dimension in (384, 768):
        config = tomllib.loads(
            runner.render_known_target_config(replace(model, dimension=dimension))
        )
        assert config["config_version"] == CONFIG_VERSION
        assert config["backend"]["name"] == "sqlite"
        assert config["embeddings"]["similarity_index"] == "exact"
        assert config["embeddings"]["indexing"]["max_text_chars"] == 4000
        assert config["daemon"]["enabled"] is False
        assert config["query_daemon"]["enabled"] is False


def test_successful_but_invalid_response_is_retried(tmp_path: Path) -> None:
    """Do not treat exit zero as qualified output during resume.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary workspace.

    Returns
    -------
    None
    """
    command = [sys.executable, "-c", "print('not JSON')"]
    operation = tmp_path / "operation"
    result = runner.execute_operation(command, tmp_path, operation, 5)
    with pytest.raises(ValueError):
        runner.operation_payload(result)
    result["valid_response"] = False
    runner.write_json(operation / "result.json", result)
    retried = runner.execute_operation(command, tmp_path, operation, 5)
    assert retried["exit_code"] == 0
    assert len(tuple(operation.glob("attempt-*"))) == 2
