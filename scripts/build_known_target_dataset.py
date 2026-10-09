"""Generate source-derived cases from immutable Git revisions.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.known_target_quality import (
    INTENTS,
    Case,
    Target,
    canonical_json,
    case_payload,
    digest_bytes,
    invalid,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def git_bytes(root: Path, *args: str) -> bytes:
    """Read Git evidence without changing a checkout.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.
    *args : str
        Git command arguments.

    Returns
    -------
    bytes
        Exact command output.
    """
    return subprocess.run(
        [shutil.which("git") or "/usr/bin/git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


def python_locations(
    tree: ast.AST,
) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
    """Visit definitions in deterministic source order.

    Parameters
    ----------
    tree : ast.AST
        Parsed module or nested definition.

    Yields
    ------
    collections.abc.Iterator
        Definitions including methods and nested functions.
    """
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield child
        yield from python_locations(child)


def literal_error_messages(tree: ast.AST) -> tuple[str, ...]:
    """Read literal raise arguments or immediately preceding message assignments.

    Parameters
    ----------
    tree : ast.AST
        Owning definition, excluding nested definitions.

    Returns
    -------
    tuple[str, ...]
        Literal messages with no interpolated or inferred runtime values.
    """
    messages: list[str] = []
    for _field, value in ast.iter_fields(tree):
        if not isinstance(value, list):
            continue
        previous: ast.AST | None = None
        for node in value:
            if not isinstance(node, ast.AST):
                continue
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and node.exc.args
            ):
                argument = node.exc.args[0]
                if (
                    isinstance(argument, ast.Name)
                    and isinstance(previous, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == argument.id
                        for target in previous.targets
                    )
                ):
                    argument = previous.value
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    message = argument.value.strip()
                    if len(message) >= 12 and "\n" not in message:
                        messages.append(message)
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                messages.extend(literal_error_messages(node))
            previous = node
    return tuple(dict.fromkeys(messages))


def markdown_headings(source: bytes) -> tuple[tuple[int, str], ...]:
    """Extract ATX headings while respecting Markdown fence type and length.

    Parameters
    ----------
    source : bytes
        Markdown source blob.

    Returns
    -------
    tuple[tuple[int, str], ...]
        Source heading lines and titles with sufficient query text.
    """
    headings: list[tuple[int, str]] = []
    fence = ""
    for lineno, line in enumerate(
        source.decode("utf-8", errors="replace").splitlines(), 1
    ):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if marker:
            token, tail = marker.groups()
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not tail.strip():
                fence = ""
            continue
        if not fence and (match := re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)):
            heading = match[1].strip()
            if len(heading) >= 8:
                headings.append((lineno, heading))
    return tuple(headings)


def source_cases(repo: str, commit: str, path: str, source: bytes) -> tuple[Case, ...]:
    """Derive queries only from literal source facts.

    Parameters
    ----------
    repo : str
        Repository label.
    commit : str
        Exact source revision.
    path : str
        Repository-relative file path.
    source : bytes
        Git blob contents.

    Returns
    -------
    tuple[Case, ...]
        Automatically derived known-target cases; unsupported files yield none.
    """
    cases: list[Case] = []
    source_digest = digest_bytes(source)

    def add(intent: str, query: str, target: Target, rule: str) -> None:
        """Add a deterministic case from one source witness.

        Parameters
        ----------
        intent : str
            Query category.
        query : str
            Source-derived text.
        target : Target
            Expected location.
        rule : str
            Derivation rule.

        Returns
        -------
        None
        """
        identity = digest_bytes(
            canonical_json(
                [repo, commit, intent, query, target.path, target.line, rule]
            ).encode()
        )[:20]
        cases.append(
            Case(
                f"{repo}-{intent}-{identity}",
                repo,
                commit,
                intent,
                query,
                "docs" if target.kind == "documentation" else "emb",
                (target,),
                {"rule": rule, "source_sha256": source_digest},
            )
        )

    if path.endswith(".py"):
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return ()
        module_doc = ast.get_docstring(tree)
        if module_doc:
            summary = module_doc.splitlines()[0].strip()
            if len(summary) >= 15:
                add(
                    "architecture_lookup",
                    f"Where is this component defined: {summary}",
                    Target(path, 0, "file"),
                    "module_docstring",
                )
        for definition in python_locations(tree):
            if definition.name.startswith("_"):
                continue
            target = Target(path, definition.lineno, "symbol")
            add("symbol_lookup", definition.name, target, "python_definition")
            doc = ast.get_docstring(definition)
            if doc and len(doc.splitlines()[0].strip()) >= 15:
                add(
                    "task_lookup",
                    f"Where is this behavior implemented: {doc.splitlines()[0].strip()}",
                    target,
                    "definition_docstring",
                )
            for message in literal_error_messages(definition):
                add("error_or_trace_lookup", message, target, "literal_raise")
    elif path.endswith(".md"):
        for lineno, heading in markdown_headings(source):
            add(
                "docs_lookup",
                f"Documentation about {heading}",
                Target(path, lineno, "documentation"),
                "markdown_heading",
            )
    return tuple(cases)


def repository_candidates(root: Path, repo: str, commit: str) -> tuple[Case, ...]:
    """Read production source candidates from a pinned Git tree.

    Parameters
    ----------
    root : pathlib.Path
        Repository containing the revision.
    repo : str
        Stable repository label.
    commit : str
        Exact revision.

    Returns
    -------
    tuple[Case, ...]
        Deterministic source-derived candidates.
    """
    paths = (
        git_bytes(root, "ls-tree", "-r", "--name-only", commit).decode().splitlines()
    )
    cases: list[Case] = []
    excluded = {"tests", "fixtures", "benchmarks", "_archive", "node_modules", "vendor"}
    for path in paths:
        if not path.endswith((".py", ".md")) or excluded.intersection(Path(path).parts):
            continue
        source = git_bytes(root, "show", f"{commit}:{path}")
        cases.extend(source_cases(repo, commit, path, source))
    return tuple(cases)


def build_dataset(manifest: Path, output: Path, per_intent: int) -> int:
    """Generate balanced cases, failing rather than inventing missing categories.

    Parameters
    ----------
    manifest : pathlib.Path
        Local repository locator manifest.
    output : pathlib.Path
        New dataset path, never overwritten.
    per_intent : int
        Required cases in each category and repository.

    Returns
    -------
    int
        Generated case count.

    Raises
    ------
    ValueError
        A repository has insufficient source-verifiable cases.
    """
    if per_intent < 1:
        invalid("Cases per intent must be positive")
    rows = json.loads(manifest.read_text(encoding="utf-8"))["repositories"]
    selected: list[Case] = []
    labels: set[str] = set()
    for row in rows:
        repo = row["label"]
        if repo in labels:
            invalid("Duplicate repository label")
        labels.add(repo)
        root = Path(row["path"]).expanduser().resolve()
        revision = str(row.get("commit", "HEAD"))
        commit = git_bytes(root, "rev-parse", f"{revision}^{{commit}}").decode().strip()
        candidates = repository_candidates(root, repo, commit)
        for intent in INTENTS:
            pool = sorted(
                (case for case in candidates if case.intent == intent),
                key=lambda case: case.id,
            )
            # Avoid identical query text within one repository and category.
            unique = {case.query: case for case in reversed(pool)}
            chosen = sorted(unique.values(), key=lambda case: case.id)[:per_intent]
            if len(chosen) < per_intent:
                invalid(
                    f"{repo}: only {len(chosen)} verified {intent} cases; need {per_intent}"
                )
            selected.extend(chosen)
    if not selected:
        invalid("No repositories selected")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        for case in selected:
            stream.write(canonical_json(case_payload(case)) + "\n")
    return len(selected)


def main(argv: list[str] | None = None) -> int:
    """Generate an automatic dataset from a locator manifest.

    Parameters
    ----------
    argv : list[str] | None, optional
        CLI arguments.

    Returns
    -------
    int
        Zero after successful generation.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-intent", type=int, default=5)
    args = parser.parse_args(argv)
    count = build_dataset(args.repo_manifest, args.output, args.per_intent)
    print(f"Generated {count} source-verified cases: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
