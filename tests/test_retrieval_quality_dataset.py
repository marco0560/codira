"""Tests for retrieval-quality dataset generation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts import build_retrieval_quality_dataset as dataset

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _repo(tmp_path: Path) -> dataset.QualityRepository:
    """
    Build a repository fixture.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository path.

    Returns
    -------
    scripts.build_retrieval_quality_dataset.QualityRepository
        Repository fixture.
    """

    return dataset.QualityRepository(
        index=1,
        label="demo",
        path=tmp_path,
        github_owner="owner",
        github_repo="repo",
    )


def test_parse_git_log_examples_filters_large_commits(tmp_path: Path) -> None:
    """
    Parse local Git history examples and reject overbroad labels.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository path.

    Returns
    -------
    None
        The test asserts only bounded changed-file examples are kept.
    """

    text = (
        "\x1eabc123\x00Fix request timeout\x00Handle timeout edge case\n"
        "src/client.py\n"
        "tests/test_client.py\n"
        "\x1edef456\x00Rewrite world\x00Too broad\n"
        "a.py\nb.py\nc.py\n"
    )

    examples = dataset.parse_git_log_examples(
        text,
        repo=_repo(tmp_path),
        max_examples=10,
        min_changed_files=1,
        max_changed_files=2,
    )

    assert len(examples) == 1
    assert examples[0].example_id == "demo-git-abc123"
    assert examples[0].query == "Fix request timeout\n\nHandle timeout edge case"
    assert examples[0].expected_paths == ("src/client.py", "tests/test_client.py")
    assert examples[0].provenance == {"commit": "abc123"}


def test_write_examples_serializes_jsonl(tmp_path: Path) -> None:
    """
    Write dataset rows as stable JSON Lines.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory.

    Returns
    -------
    None
        The test asserts the persisted row keeps labels and provenance.
    """

    output = tmp_path / "dataset.jsonl"
    example = dataset.QualityExample(
        example_id="demo",
        repo="repo",
        repo_path="/tmp/repo",
        source="git_commit",
        query="fix parser",
        expected_paths=("src/parser.py",),
        provenance={"commit": "abc"},
    )

    dataset.write_examples(output, (example,))

    row = json.loads(output.read_text(encoding="utf-8"))
    assert row == {
        "expected_paths": ["src/parser.py"],
        "id": "demo",
        "provenance": {"commit": "abc"},
        "query": "fix parser",
        "repo": "repo",
        "repo_path": "/tmp/repo",
        "schema_version": 1,
        "source": "git_commit",
    }


def test_collect_github_pr_examples_uses_changed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Convert GitHub pull request metadata into labeled examples.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository path.
    monkeypatch : pytest.MonkeyPatch
        Monkeypatch fixture.

    Returns
    -------
    None
        The test asserts PR title/body and changed filenames form one example.
    """

    def fake_gh(endpoint: str) -> object:
        """
        Return fake GitHub API pages.

        Parameters
        ----------
        endpoint : str
            API endpoint.

        Returns
        -------
        object
            Fake ``gh api --slurp`` payload.
        """

        if endpoint.startswith("/repos/owner/repo/pulls?"):
            return [
                [
                    {
                        "number": 42,
                        "title": "Fix parser",
                        "body": "Handle escaped strings",
                        "html_url": "https://example.test/pr/42",
                    }
                ]
            ]
        return [[{"filename": "src/parser.py"}, {"filename": "./tests/test_parser.py"}]]

    monkeypatch.setattr(dataset, "_gh_api_json", fake_gh)

    examples = dataset.collect_github_pr_examples(
        _repo(tmp_path),
        max_examples=10,
        min_changed_files=1,
        max_changed_files=5,
    )

    assert len(examples) == 1
    assert examples[0].source == "github_pr"
    assert examples[0].query == "Fix parser\n\nHandle escaped strings"
    assert examples[0].expected_paths == ("src/parser.py", "tests/test_parser.py")
