#!/usr/bin/env python3
"""Build retrieval-quality datasets from Git and GitHub provenance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.scriptlib import safe_slug

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_REPO_MANIFEST = Path("benchmarks/retrieval-quality-repos.local.json")
DEFAULT_OUTPUT = Path(".artifacts/retrieval-quality/dataset.jsonl")
DEFAULT_MAX_EXAMPLES_PER_REPO = 100
DEFAULT_MAX_CHANGED_FILES = 20
DEFAULT_MIN_CHANGED_FILES = 1
DEFAULT_GIT_SCAN_LIMIT = 500
SOURCES = ("auto", "github", "git")


@dataclass(frozen=True)
class QualityRepository:
    """
    Repository entry used for retrieval-quality dataset generation.

    Parameters
    ----------
    index : int
        Manifest order.
    label : str
        Stable repository label.
    path : pathlib.Path
        Local repository root.
    github_owner : str | None
        Optional GitHub owner used for PR and issue collection.
    github_repo : str | None
        Optional GitHub repository name used for PR and issue collection.
    default_branch : str | None
        Optional default branch name.

    Returns
    -------
    None
    """

    index: int
    label: str
    path: Path
    github_owner: str | None = None
    github_repo: str | None = None
    default_branch: str | None = None


@dataclass(frozen=True)
class QualityExample:
    """
    One labeled retrieval query.

    Parameters
    ----------
    example_id : str
        Stable example identifier.
    repo : str
        Repository label.
    repo_path : str
        Absolute local repository path.
    source : str
        Example source such as ``github_pr`` or ``git_commit``.
    query : str
        Natural-language retrieval query.
    expected_paths : tuple[str, ...]
        Repo-relative files considered relevant.
    provenance : dict[str, object]
        Machine-readable source metadata.

    Returns
    -------
    None
    """

    example_id: str
    repo: str
    repo_path: str
    source: str
    query: str
    expected_paths: tuple[str, ...]
    provenance: dict[str, object]


def positive_int(value: str) -> int:
    """
    Parse a positive integer CLI value.

    Parameters
    ----------
    value : str
        Raw command-line value.

    Returns
    -------
    int
        Parsed positive integer.

    Raises
    ------
    argparse.ArgumentTypeError
        Raised when ``value`` is not a positive integer.
    """

    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "value must be an integer"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed < 1:
        msg = "value must be >= 1"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def read_repositories(path: Path) -> tuple[QualityRepository, ...]:
    """
    Read retrieval-quality repository entries.

    Parameters
    ----------
    path : pathlib.Path
        Repository manifest path.

    Returns
    -------
    tuple[QualityRepository, ...]
        Parsed repository entries.
    """

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        msg = f"repository manifest must contain an object: {path}"
        raise TypeError(msg)
    repositories = payload.get("repositories")
    if not isinstance(repositories, list):
        msg = f"repository manifest must contain a repositories list: {path}"
        raise TypeError(msg)

    entries: list[QualityRepository] = []
    for index, row in enumerate(repositories, start=1):
        if not isinstance(row, dict):
            msg = f"repository entry must be an object at index {index}"
            raise TypeError(msg)
        repo_path = Path(str(row["path"])).expanduser().resolve()
        entries.append(
            QualityRepository(
                index=index,
                label=str(row.get("label") or repo_path.name),
                path=repo_path,
                github_owner=_optional_str(row.get("github_owner")),
                github_repo=_optional_str(row.get("github_repo")),
                default_branch=_optional_str(row.get("default_branch")),
            )
        )
    return tuple(entries)


def _optional_str(value: object) -> str | None:
    """
    Return a stripped string or ``None``.

    Parameters
    ----------
    value : object
        Candidate value.

    Returns
    -------
    str | None
        Non-empty string value, otherwise ``None``.
    """

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_path(path: str) -> str:
    """
    Normalize a repository-relative file path.

    Parameters
    ----------
    path : str
        Raw path from Git, GitHub, or Codira output.

    Returns
    -------
    str
        Normalized path using forward slashes and no leading ``./``.
    """

    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def selected_paths(
    paths: Iterable[str],
    *,
    min_changed_files: int,
    max_changed_files: int,
) -> tuple[str, ...]:
    """
    Return usable changed paths for one example.

    Parameters
    ----------
    paths : collections.abc.Iterable[str]
        Candidate changed paths.
    min_changed_files : int
        Minimum number of changed paths required.
    max_changed_files : int
        Maximum number of changed paths allowed.

    Returns
    -------
    tuple[str, ...]
        Deduplicated path tuple, or an empty tuple when limits reject it.
    """

    normalized = tuple(
        dict.fromkeys(path for raw in paths if (path := normalize_path(raw)))
    )
    if len(normalized) < min_changed_files or len(normalized) > max_changed_files:
        return ()
    return normalized


def example_query(title: str, body: str = "") -> str:
    """
    Build a compact natural-language query from title and body text.

    Parameters
    ----------
    title : str
        Primary text.
    body : str, optional
        Secondary text.

    Returns
    -------
    str
        Query text with blank lines collapsed.
    """

    parts = [line.strip() for line in (title, body) if line and line.strip()]
    return "\n\n".join(parts).strip()


def parse_git_log_examples(
    text: str,
    *,
    repo: QualityRepository,
    max_examples: int,
    min_changed_files: int,
    max_changed_files: int,
) -> tuple[QualityExample, ...]:
    """
    Parse ``git log`` output into retrieval examples.

    Parameters
    ----------
    text : str
        Output produced by ``git log`` with record and field separators.
    repo : QualityRepository
        Repository metadata.
    max_examples : int
        Maximum examples to return.
    min_changed_files : int
        Minimum changed path count.
    max_changed_files : int
        Maximum changed path count.

    Returns
    -------
    tuple[QualityExample, ...]
        Parsed commit-derived examples.
    """

    examples: list[QualityExample] = []
    for record in text.split("\x1e"):
        stripped = record.strip()
        if not stripped:
            continue
        header, _, path_text = stripped.partition("\n")
        fields = header.split("\x00", 2)
        if len(fields) != 3:
            continue
        commit_hash, subject, body = fields
        query = example_query(subject, body)
        paths = selected_paths(
            path_text.splitlines(),
            min_changed_files=min_changed_files,
            max_changed_files=max_changed_files,
        )
        if not query or not paths:
            continue
        examples.append(
            QualityExample(
                example_id=safe_slug(f"{repo.label}-git-{commit_hash[:12]}"),
                repo=repo.label,
                repo_path=str(repo.path),
                source="git_commit",
                query=query,
                expected_paths=paths,
                provenance={"commit": commit_hash},
            )
        )
        if len(examples) >= max_examples:
            break
    return tuple(examples)


def collect_git_examples(
    repo: QualityRepository,
    *,
    max_examples: int,
    min_changed_files: int,
    max_changed_files: int,
    scan_limit: int,
) -> tuple[QualityExample, ...]:
    """
    Collect local Git commit examples.

    Parameters
    ----------
    repo : QualityRepository
        Repository metadata.
    max_examples : int
        Maximum examples to return.
    min_changed_files : int
        Minimum changed path count.
    max_changed_files : int
        Maximum changed path count.
    scan_limit : int
        Number of recent commits to scan.

    Returns
    -------
    tuple[QualityExample, ...]
        Commit-derived examples.

    Raises
    ------
    RuntimeError
        Raised when ``git log`` fails.
    """

    command = (
        "git",
        "-C",
        str(repo.path),
        "log",
        "--no-merges",
        f"-n{scan_limit}",
        "--format=%x1e%H%x00%s%x00%b",
        "--name-only",
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        msg = f"git log failed for {repo.label}{suffix}"
        raise RuntimeError(msg)
    return parse_git_log_examples(
        completed.stdout,
        repo=repo,
        max_examples=max_examples,
        min_changed_files=min_changed_files,
        max_changed_files=max_changed_files,
    )


def _gh_api_json(endpoint: str) -> object:
    """
    Run ``gh api`` and decode JSON output.

    Parameters
    ----------
    endpoint : str
        GitHub REST API endpoint.

    Returns
    -------
    object
        Decoded JSON payload.

    Raises
    ------
    RuntimeError
        Raised when the GitHub CLI fails or emits invalid JSON.
    """

    command = ("gh", "api", "--paginate", "--slurp", endpoint)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        msg = f"gh api failed for {endpoint}{suffix}"
        raise RuntimeError(msg)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        msg = f"gh api returned invalid JSON for {endpoint}"
        raise RuntimeError(msg) from exc


def _flatten_paginated_array(payload: object) -> tuple[dict[str, object], ...]:
    """
    Flatten ``gh api --slurp`` page arrays.

    Parameters
    ----------
    payload : object
        Decoded GitHub CLI payload.

    Returns
    -------
    tuple[dict[str, object], ...]
        Flattened object rows.
    """

    rows: list[dict[str, object]] = []
    if isinstance(payload, list):
        pages = payload if payload and isinstance(payload[0], list) else [payload]
        for page in pages:
            if not isinstance(page, list):
                continue
            rows.extend(
                cast("dict[str, object]", item)
                for item in page
                if isinstance(item, dict)
            )
    return tuple(rows)


def collect_github_pr_examples(
    repo: QualityRepository,
    *,
    max_examples: int,
    min_changed_files: int,
    max_changed_files: int,
) -> tuple[QualityExample, ...]:
    """
    Collect GitHub pull-request examples.

    Parameters
    ----------
    repo : QualityRepository
        Repository metadata with GitHub owner and name.
    max_examples : int
        Maximum examples to return.
    min_changed_files : int
        Minimum changed path count.
    max_changed_files : int
        Maximum changed path count.

    Returns
    -------
    tuple[QualityExample, ...]
        PR-derived examples.

    Raises
    ------
    RuntimeError
        Raised when GitHub metadata cannot be fetched.
    """

    if not repo.github_owner or not repo.github_repo:
        return ()

    pull_endpoint = (
        f"/repos/{repo.github_owner}/{repo.github_repo}/pulls"
        "?state=closed&sort=updated&direction=desc&per_page=100"
    )
    pulls = _flatten_paginated_array(_gh_api_json(pull_endpoint))
    examples: list[QualityExample] = []
    for pull in pulls:
        number_raw = pull.get("number", 0)
        number = int(number_raw) if isinstance(number_raw, int | str) else 0
        if not number:
            continue
        title = str(pull.get("title") or "")
        body = str(pull.get("body") or "")
        query = example_query(title, body)
        if not query:
            continue
        files_endpoint = (
            f"/repos/{repo.github_owner}/{repo.github_repo}/pulls/"
            f"{number}/files?per_page=100"
        )
        files = _flatten_paginated_array(_gh_api_json(files_endpoint))
        paths = selected_paths(
            (str(file_row.get("filename") or "") for file_row in files),
            min_changed_files=min_changed_files,
            max_changed_files=max_changed_files,
        )
        if not paths:
            continue
        examples.append(
            QualityExample(
                example_id=safe_slug(f"{repo.label}-github-pr-{number}"),
                repo=repo.label,
                repo_path=str(repo.path),
                source="github_pr",
                query=query,
                expected_paths=paths,
                provenance={
                    "owner": repo.github_owner,
                    "repo": repo.github_repo,
                    "pr": number,
                    "url": str(pull.get("html_url") or ""),
                },
            )
        )
        if len(examples) >= max_examples:
            break
    return tuple(examples)


def write_examples(path: Path, examples: Sequence[QualityExample]) -> None:
    """
    Write examples as JSON Lines.

    Parameters
    ----------
    path : pathlib.Path
        Output path.
    examples : collections.abc.Sequence[QualityExample]
        Examples to serialize.

    Returns
    -------
    None
        The file is written.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for example in examples:
            output.write(
                json.dumps(
                    {
                        "schema_version": 1,
                        "id": example.example_id,
                        "repo": example.repo,
                        "repo_path": example.repo_path,
                        "source": example.source,
                        "query": example.query,
                        "expected_paths": list(example.expected_paths),
                        "provenance": example.provenance,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def build_parser() -> argparse.ArgumentParser:
    """
    Build the dataset-generator argument parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Configured parser.
    """

    parser = argparse.ArgumentParser(
        description="Build a Codira retrieval-quality dataset from Git and GitHub."
    )
    parser.add_argument("--repo-manifest", type=Path, default=DEFAULT_REPO_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", choices=SOURCES, default="auto")
    parser.add_argument(
        "--max-examples-per-repo",
        type=positive_int,
        default=DEFAULT_MAX_EXAMPLES_PER_REPO,
    )
    parser.add_argument(
        "--min-changed-files",
        type=positive_int,
        default=DEFAULT_MIN_CHANGED_FILES,
    )
    parser.add_argument(
        "--max-changed-files",
        type=positive_int,
        default=DEFAULT_MAX_CHANGED_FILES,
    )
    parser.add_argument(
        "--git-scan-limit", type=positive_int, default=DEFAULT_GIT_SCAN_LIMIT
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    Run retrieval-quality dataset generation.

    Parameters
    ----------
    argv : list[str] | None, optional
        Command-line arguments excluding the executable.

    Returns
    -------
    int
        Zero when examples were written.

    Raises
    ------
    ValueError
        Raised when manifests are malformed.
    RuntimeError
        Raised when selected metadata sources fail.
    """

    args = build_parser().parse_args(argv)
    if args.min_changed_files > args.max_changed_files:
        msg = "--min-changed-files must be <= --max-changed-files"
        raise SystemExit(msg)

    examples: list[QualityExample] = []
    for repo in read_repositories(args.repo_manifest):
        repo_examples: tuple[QualityExample, ...] = ()
        if args.source in {"auto", "github"} and repo.github_owner and repo.github_repo:
            repo_examples = collect_github_pr_examples(
                repo,
                max_examples=args.max_examples_per_repo,
                min_changed_files=args.min_changed_files,
                max_changed_files=args.max_changed_files,
            )
        if args.source == "github":
            examples.extend(repo_examples)
            continue
        remaining = args.max_examples_per_repo - len(repo_examples)
        if remaining > 0:
            git_examples = collect_git_examples(
                repo,
                max_examples=remaining,
                min_changed_files=args.min_changed_files,
                max_changed_files=args.max_changed_files,
                scan_limit=args.git_scan_limit,
            )
            repo_examples = (*repo_examples, *git_examples)
        examples.extend(repo_examples)

    write_examples(args.output, examples)
    print(f"Examples: {len(examples)}")
    print(f"Dataset: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
