#!/usr/bin/env python3
"""
Codira demo script.

Demonstrates end-to-end usage of the Codira CLI on a user-selected
repository using explicit path resolution (issue #19 compliant).

Parameters
----------
None

Returns
-------
None

Notes
-----
All Codira commands are executed with explicit ``--path`` to decouple
target repository from the current working directory.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Any

# --- deterministic codira resolution ---

project_root = Path(__file__).resolve().parents[1]
venv_candidate = project_root / ".venv" / "bin" / "codira"
path_candidate = which("codira")

if venv_candidate.exists():
    CODIRA_BIN = venv_candidate
elif path_candidate:
    CODIRA_BIN = Path(path_candidate)
else:
    msg = f"ERROR: codira executable not found.\nTried:\n  - {venv_candidate}\n  - PATH lookup"
    raise SystemExit(msg)

CODIRA: list[str] = [str(CODIRA_BIN)]


# --- helpers ---


def section(title: str) -> None:
    """
    Print a formatted section header.

    Parameters
    ----------
    title : str
        Section title to display.

    Returns
    -------
    None
    """
    print()
    print(f"=== {title} ===")


def quote_cmd(cmd: list[str]) -> str:
    """
    Quote a command for display.

    Parameters
    ----------
    cmd : list[str]
        Command parts.

    Returns
    -------
    str
        Shell-escaped command string.
    """
    return " ".join(shlex.quote(part) for part in cmd)


def run(
    cmd: list[str],
    path: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """
    Execute a Codira command.

    Parameters
    ----------
    cmd : list[str]
        Codira subcommand and arguments.
    path : Path | None
        Target repository path passed via ``--path``.
    check : bool
        Whether to exit on non-zero return code.
    capture : bool
        Whether to capture and print stdout/stderr.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed process object.

    Raises
    ------
    SystemExit
        If command fails and ``check`` is True.
    """
    full_cmd = CODIRA + cmd
    if path is not None:
        full_cmd += ["--path", str(path)]

    print(f"> {quote_cmd(full_cmd)}")

    proc = subprocess.run(
        full_cmd,
        text=True,
        capture_output=capture,
    )

    if capture:
        if proc.stdout:
            print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)

    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)

    return proc


# --- codira interaction layer ---


def _symlist_json(repo: Path) -> dict[str, Any] | None:
    """
    Execute ``codira symlist --json`` and parse output.

    Parameters
    ----------
    repo : Path
        Target repository.

    Returns
    -------
    dict[str, Any] | None
        Parsed JSON result, or None on failure.
    """
    section("Discover candidates via symlist --json")

    cmd = CODIRA + ["symlist", "--json", "--limit", "100", "--path", str(repo)]

    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
    )

    print(f"> {quote_cmd(cmd)}")

    if proc.stdout:
        print(proc.stdout)

    if proc.returncode != 0:
        return None

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(raw, dict):
        return None

    data: dict[str, Any] = raw
    return data


def _metric_total(item: dict[str, Any], key: str) -> int:
    """
    Extract a graph metric total from a symbol inventory item.

    Parameters
    ----------
    item : dict[str, Any]
        Parsed symbol inventory item.
    key : str
        Metric field name.

    Returns
    -------
    int
        Metric total when present, otherwise zero.
    """
    metric = item.get(key)
    if not isinstance(metric, dict):
        return 0

    total = metric.get("total", 0)
    if isinstance(total, int):
        return total

    return 0


def _repo_relative_prefix(repo: Path, file_path: str) -> str:
    """
    Convert a symbol inventory file path into a repo-root-relative prefix.

    Parameters
    ----------
    repo : Path
        Target repository.
    file_path : str
        File path emitted by ``codira symlist --json``.

    Returns
    -------
    str
        Repo-root-relative file prefix.

    Raises
    ------
    SystemExit
        If the file path cannot be expressed under the repository root.
    """
    repo_root = repo.resolve()
    path = Path(file_path)
    if not path.is_absolute():
        path = repo_root / path

    try:
        return path.resolve(strict=False).relative_to(repo_root).as_posix()
    except ValueError as exc:
        msg = f"ERROR: symlist returned file outside repository: {file_path}"
        raise SystemExit(msg) from exc


def _has_symbol(repo: Path, name: str) -> bool:
    """
    Check if a symbol exists.

    Parameters
    ----------
    repo : Path
        Target repository.
    name : str
        Symbol name.

    Returns
    -------
    bool
        True if symbol exists.
    """
    proc = subprocess.run(
        CODIRA + ["sym", name, "--path", str(repo)],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and "No symbol found:" not in proc.stdout


def _score_inventory_item(item: dict[str, Any]) -> int:
    """
    Score a symbol inventory item by graph connectivity.

    Parameters
    ----------
    item : dict[str, Any]
        Parsed symbol inventory item.

    Returns
    -------
    int
        Connectivity score.
    """
    return (
        _metric_total(item, "calls_out") * 2
        + _metric_total(item, "calls_in") * 2
        + _metric_total(item, "refs_out")
        + _metric_total(item, "refs_in") * 2
    )


def _extract_candidates(repo: Path, data: dict[str, Any]) -> list[tuple[str, str, int]]:
    """
    Extract candidate symbols from symlist output.

    Parameters
    ----------
    repo : Path
        Target repository.
    data : dict[str, Any]
        Parsed symlist JSON.

    Returns
    -------
    list[tuple[str, str, int]]
        Candidate symbol name, repo-root-relative file prefix, and score.
    """
    candidates: list[tuple[str, str, int]] = []

    for item in data.get("symbols", []):
        if not isinstance(item, dict) or item.get("type") not in {"function", "method"}:
            continue

        name = item.get("name")
        file_path = item.get("file")
        if not isinstance(name, str) or not isinstance(file_path, str):
            continue

        score = _score_inventory_item(item)
        if score <= 0:
            continue

        prefix = _repo_relative_prefix(repo, file_path)
        candidates.append((name, prefix, score))

    return candidates


def discover_symbol_with_edges(repo: Path) -> tuple[str, str]:
    """
    Discover a symbol with meaningful graph connectivity.

    Parameters
    ----------
    repo : Path
        Target repository.

    Returns
    -------
    tuple[str, str]
        Selected symbol name and repo-root-relative file prefix.

    Raises
    ------
    SystemExit
        If no suitable symbol is found.
    """
    data = _symlist_json(repo)
    if not data:
        msg = "ERROR: symlist discovery failed"
        raise SystemExit(msg)

    best_name: str | None = None
    best_prefix: str | None = None
    best_score = -1

    for name, prefix, score in _extract_candidates(repo, data):
        if not _has_symbol(repo, name):
            continue

        print(f"> scored candidate: {name} -> {score}")

        if score > best_score:
            best_score = score
            best_name = name
            best_prefix = prefix

    if best_name and best_prefix:
        print(f"Selected best symbol: {best_name} (score={best_score})")
        return best_name, best_prefix

    msg = "ERROR: no suitable symbol found"
    raise SystemExit(msg)


# --- main ---


def main() -> None:
    """
    Run the Codira demo workflow.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    section("Codira Demo Script")

    section("STEP 0 — Version")
    run(["--version"], capture=True)

    section("STEP 1 — Help")
    run(["--help"], capture=True)

    repo_input = input("Enter path to target repository: ").strip()
    repo = Path(repo_input).resolve()

    if not repo.is_dir():
        msg = "Invalid repository path"
        raise SystemExit(msg)

    print(f"Using repository: {repo}")

    section("STEP 2 — Index")
    run(["index"], path=repo, capture=True)

    section("STEP 3 — Plugins")
    run(["plugins"], path=repo, capture=True)

    section("STEP 4 — Capabilities")
    run(["caps"], path=repo, capture=True)

    section("STEP 5 — Coverage")
    run(["cov"], path=repo, check=False, capture=True)

    section("STEP 6 — Discover symbol")
    symbol, symbol_prefix = discover_symbol_with_edges(repo)
    print(f"Chosen symbol: {symbol}")

    section("STEP 7 — Symbol inventory prefix example")
    run(
        ["symlist", "--prefix", symbol_prefix, "--limit", "100"],
        path=repo,
        capture=True,
    )

    section("STEP 8 — Symbol lookup")
    run(["sym", symbol], path=repo, capture=True)

    section("STEP 9 — Embeddings")
    run(["emb", "core logic"], path=repo, check=False, capture=True)

    section("STEP 10 — Context")
    run(["ctx", "core logic"], path=repo, capture=True)

    section("STEP 11 — Context (prompt)")
    run(["ctx", "--prompt", "improve test coverage"], path=repo, capture=True)

    section("STEP 12 — Context (json)")
    run(["ctx", "--json", "core logic"], path=repo, capture=True)

    section("STEP 13 — Context (explain)")
    run(["ctx", "--explain", "ranking"], path=repo, capture=True)

    section("STEP 14 — Calls")
    run(["calls", symbol], path=repo, check=False, capture=True)

    section("STEP 15 — Calls tree")
    run(["calls", symbol, "--tree"], path=repo, check=False, capture=True)

    section("STEP 16 — Calls dot")
    run(["calls", symbol, "--tree", "--dot"], path=repo, check=False, capture=True)

    section("STEP 17 — Calls incoming")
    run(["calls", symbol, "--incoming"], path=repo, check=False, capture=True)

    section("STEP 18 — Refs")
    run(["refs", symbol], path=repo, check=False, capture=True)

    section("STEP 19 — Refs incoming tree")
    run(["refs", symbol, "--incoming", "--tree"], path=repo, check=False, capture=True)

    section("STEP 20 — Refs dot")
    run(["refs", symbol, "--tree", "--dot"], path=repo, check=False, capture=True)

    section("STEP 21 — Audit gate")
    ans = input("Does the repo use NumPy docstrings? [y/N]: ").lower()

    if ans == "y":
        section("STEP 22 — Audit")
        run(["audit"], path=repo, check=False, capture=True)

        section("STEP 23 — Audit JSON")
        run(["audit", "--json"], path=repo, check=False, capture=True)
    else:
        print("Skipping audit (likely noisy)")

    section("DEMO COMPLETE")


if __name__ == "__main__":
    main()
