"""Tests for retrieval-quality benchmark helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts import run_retrieval_quality_benchmark as quality
from scripts.run_final_embedding_model_campaign import ModelEntry, RepositoryEntry

if TYPE_CHECKING:
    from collections.abc import Sequence


def _model() -> ModelEntry:
    """
    Build a model fixture.

    Parameters
    ----------
    None

    Returns
    -------
    scripts.run_final_embedding_model_campaign.ModelEntry
        Model fixture.
    """

    return ModelEntry(
        id="demo-model",
        engine="onnx",
        model="demo/model",
        version="1",
        dimension=384,
        precision="float32",
        config={
            "model_path": ".codira/models/demo/model.onnx",
            "tokenizer_path": ".codira/models/demo/tokenizer.json",
            "provider": "CPUExecutionProvider",
        },
    )


def test_score_paths_computes_recall_mrr_and_ndcg() -> None:
    """
    Score ranked paths against expected labels.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts hit counts and rank-sensitive metrics.
    """

    score = quality.score_paths(
        ("src/a.py", "src/b.py"),
        ("README.md", "src/b.py", "src/a.py"),
        k=3,
    )

    assert score.hits == 2
    assert score.hit_any is True
    assert score.recall == 1.0
    assert score.mrr == 0.5
    assert round(score.ndcg, 4) == 0.6934


def test_score_paths_matches_absolute_retrieved_suffixes() -> None:
    """
    Score absolute result paths against repo-relative expected paths.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts benchmark scoring accepts Codira absolute result paths
        for repo-relative labels.
    """

    score = quality.score_paths(
        ("src/parser.py", "docs/usage.md"),
        (
            "home/marco/work/demo/tests/test_parser.py",
            "home/marco/work/demo/src/parser.py",
        ),
        k=2,
    )

    assert score.hits == 1
    assert score.hit_any is True
    assert score.recall == 0.5
    assert score.mrr == 0.5


def test_extract_paths_walks_nested_payloads() -> None:
    """
    Extract Codira result paths from nested JSON rows.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts duplicate and nested paths are normalized.
    """

    payload = {
        "results": [
            {"file": "./src/a.py", "children": [{"path": "src/b.py"}]},
            {"file_path": "src/a.py"},
        ]
    }

    assert quality.extract_paths(payload) == ("src/a.py", "src/b.py")


def test_summarize_results_recomputes_stored_query_scores(tmp_path: Path) -> None:
    """
    Recompute summaries from stored paths instead of persisted score fields.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts old zero-score rows can be summarized with fixed path
        matching logic.
    """

    results_path = tmp_path / "results.jsonl"
    rows = [
        {
            "phase": "index",
            "backend": "sqlite",
            "model": "demo",
            "repo": "demo",
            "elapsed_seconds": 1.0,
        },
        {
            "phase": "emb",
            "backend": "sqlite",
            "model": "demo",
            "repo": "demo",
            "source": "git_commit",
            "elapsed_seconds": 0.5,
            "expected_paths": ["src/parser.py"],
            "retrieved_paths": ["/tmp/work/demo/src/parser.py"],
            "recall": 0.0,
            "mrr": 0.0,
            "ndcg": 0.0,
            "hit_any": False,
        },
    ]
    results_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    summary = quality.summarize_results(results_path)

    groups = summary["groups"]
    assert isinstance(groups, list)
    group = groups[0]
    assert isinstance(group, dict)
    assert group["mean_recall"] == 1.0
    assert group["mean_mrr"] == 1.0
    assert group["mean_ndcg"] == 1.0
    assert group["hit_any_rate"] == 1.0


def test_write_summary_artifacts_rescores_existing_results(tmp_path: Path) -> None:
    """
    Rewrite summary and report files from an existing result JSONL file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts summary artifacts are produced with current scoring.
    """

    results_path = tmp_path / "results.jsonl"
    rows = [
        {
            "phase": "emb",
            "backend": "sqlite",
            "model": "demo",
            "repo": "demo",
            "source": "git_commit",
            "elapsed_seconds": 0.5,
            "expected_paths": ["src/parser.py"],
            "retrieved_paths": ["/tmp/work/demo/src/parser.py"],
        },
    ]
    results_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    summary_path, report_path = quality.write_summary_artifacts(results_path)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["groups"][0]["mean_recall"] == 1.0
    assert "| sqlite | demo | demo | git_commit | emb |" in report_path.read_text(
        encoding="utf-8"
    )


def test_decode_json_from_log_tolerates_prefix_text(tmp_path: Path) -> None:
    """
    Decode a JSON object from a command log with leading text.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts the first JSON object is returned.
    """

    log_path = tmp_path / "command.log"
    log_path.write_text(
        'warning\n{"results": [{"file": "src/a.py"}]}\n', encoding="utf-8"
    )

    assert quality.decode_json_from_log(log_path) == {"results": [{"file": "src/a.py"}]}


def test_load_dataset_reads_jsonl(tmp_path: Path) -> None:
    """
    Load quality examples from JSON Lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts fields are preserved and paths normalized.
    """

    dataset_path = tmp_path / "dataset.jsonl"
    dataset_path.write_text(
        json.dumps(
            {
                "id": "one",
                "repo": "demo",
                "source": "git_commit",
                "query": "fix parser",
                "expected_paths": ["./src/parser.py"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert quality.load_dataset(dataset_path) == (
        quality.QualityExample(
            example_id="one",
            repo="demo",
            source="git_commit",
            query="fix parser",
            expected_paths=("src/parser.py",),
        ),
    )


def test_validate_dataset_repositories_rejects_partial_unknown_labels() -> None:
    """Reject a partially unmatched retrieval-quality dataset.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts an unknown label cannot be silently omitted.
    """
    examples = (
        quality.QualityExample("known", "demo", "git", "known", ("src/a.py",)),
        quality.QualityExample("unknown", "missing", "git", "unknown", ("src/b.py",)),
    )

    with pytest.raises(ValueError, match="missing"):
        quality.validate_dataset_repositories(
            examples=examples,
            repositories={
                "demo": RepositoryEntry(
                    index=0,
                    label="demo",
                    path=Path("repository"),
                )
            },
        )


def test_validate_dataset_repositories_rejects_wholly_unknown_labels() -> None:
    """Reject a wholly unmatched retrieval-quality dataset.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts no effective benchmark can be empty.
    """
    examples = (
        quality.QualityExample("unknown", "missing", "git", "unknown", ("src/a.py",)),
    )

    with pytest.raises(ValueError, match="missing"):
        quality.validate_dataset_repositories(examples=examples, repositories={})


def test_run_group_uses_isolated_config_and_output_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Plan benchmark commands with explicit generated config files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.
    monkeypatch : pytest.MonkeyPatch
        Monkeypatch fixture.

    Returns
    -------
    None
        The test asserts command vectors use artifact-isolated paths.
    """

    commands: list[tuple[str, ...]] = []

    def fake_timed_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
    ) -> quality.CommandResult:
        """
        Record a command and write a fake JSON log.

        Parameters
        ----------
        command : collections.abc.Sequence[str]
            Command vector.
        cwd : pathlib.Path
            Working directory.
        env : dict[str, str]
            Child environment.
        log_path : pathlib.Path
            Log path.

        Returns
        -------
        scripts.run_retrieval_quality_benchmark.CommandResult
            Fake successful command result.
        """

        del cwd, env
        commands.append(tuple(command))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            '{"results": [{"file": "src/parser.py"}]}\n', encoding="utf-8"
        )
        return quality.CommandResult(
            returncode=0,
            elapsed_seconds=0.1,
            log_path=log_path,
        )

    monkeypatch.setattr(quality, "timed_command", fake_timed_command)
    results_path = tmp_path / "results.jsonl"
    repo = RepositoryEntry(index=1, label="demo", path=tmp_path / "repo")
    example = quality.QualityExample(
        example_id="one",
        repo="demo",
        source="git_commit",
        query="fix parser",
        expected_paths=("src/parser.py",),
    )

    status = quality.run_group(
        codira="/tmp/codira",
        repo=repo,
        model=_model(),
        backend="sqlite",
        examples=(example,),
        artifact_root=tmp_path / "artifacts",
        results_path=results_path,
        env={},
        top_k=10,
        include_ctx=False,
        full=True,
    )

    assert status == 0
    assert commands[0][:2] == ("/tmp/codira", "index")
    assert "--config-file" in commands[0]
    assert "--output-dir" in commands[0]
    assert commands[1][:2] == ("/tmp/codira", "emb")
    assert "--config-file" in commands[1]
    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[1]["recall"] == 1.0
