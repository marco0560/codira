#!/usr/bin/env python3
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
    print()
    print(f"=== {title} ===")


def quote_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    full_cmd = CODIRA + cmd
    print(f"> {quote_cmd(full_cmd)}")
    proc = subprocess.run(
        full_cmd,
        cwd=str(cwd) if cwd else None,
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


def _ctx_json(repo: Path, query: str) -> dict[str, Any] | None:
    section(f"Discover candidates via ctx --json: {query}")
    proc = subprocess.run(
        CODIRA + ["ctx", "--json", query],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    print(f"> {quote_cmd(CODIRA + ['ctx', '--json', query])}")
    if proc.stdout:
        print(proc.stdout)

    if proc.returncode != 0:
        return None

    try:
        data: dict[str, Any] = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    else:
        return data


def _extract_candidates(data: dict[str, Any]) -> list[tuple[str, float]]:
    candidates: list[tuple[str, float]] = []

    for item in data.get("top_matches", []):
        if isinstance(item, dict) and item.get("type") in {"function", "method"}:
            name = item.get("name")
            conf = item.get("confidence", 0.0)
            if isinstance(name, str) and isinstance(conf, (int, float)):
                candidates.append((name, float(conf)))

    for item in data.get("module_expansion", []):
        if isinstance(item, dict) and item.get("type") in {"function", "method"}:
            name = item.get("name")
            if isinstance(name, str):
                candidates.append((name, 0.5))

    return candidates


def _has_symbol(repo: Path, name: str) -> bool:
    proc = subprocess.run(
        CODIRA + ["sym", name],
        cwd=repo,
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0 and "No symbol found:" not in proc.stdout


def _run_graph(repo: Path, args: list[str]) -> str:
    proc = subprocess.run(
        CODIRA + args,
        cwd=repo,
        text=True,
        capture_output=True,
    )
    return proc.stdout


def _score_candidate(repo: Path, name: str, confidence: float) -> float:
    calls = _run_graph(repo, ["calls", name])
    calls_in = _run_graph(repo, ["calls", name, "--incoming"])
    refs = _run_graph(repo, ["refs", name])
    refs_in = _run_graph(repo, ["refs", name, "--incoming"])

    score = 0.0

    if "No call edges found" not in calls:
        score += 2
    if "No call edges found" not in calls_in:
        score += 2
    if "No callable references found" not in refs:
        score += 1
    if "No callable references found" not in refs_in:
        score += 2
    if "<unresolved>" not in calls:
        score += 1

    score += confidence

    print(f"> scored candidate: {name} -> {score:.2f}")
    return score


def _select_best_symbol(
    repo: Path, candidates: list[tuple[str, float]]
) -> tuple[str | None, float]:
    best_name: str | None = None
    best_score = -1.0

    for name, confidence in candidates:
        if not _has_symbol(repo, name):
            continue

        score = _score_candidate(repo, name, confidence)

        if score > best_score:
            best_score = score
            best_name = name

    return best_name, best_score


def discover_symbol_with_edges(repo: Path) -> str:
    queries = ["core logic", "call graph", "main"]

    best_name: str | None = None
    best_score = -1.0

    for q in queries:
        data = _ctx_json(repo, q)
        if not data:
            continue

        candidates = _extract_candidates(data)
        name, score = _select_best_symbol(repo, candidates)

        if name is not None and score > best_score:
            best_name = name
            best_score = score

    if best_name:
        print(f"Selected best symbol: {best_name} (score={best_score:.2f})")
        return best_name

    msg = "ERROR: no suitable symbol found"
    raise SystemExit(msg)


# --- main ---


def main() -> None:
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
    print("NOTE: cd-based workflow (will change after issue #19)")

    section("STEP 2 — Index")
    run(["index"], cwd=repo, capture=True)

    section("STEP 3 — Plugins")
    run(["plugins"], cwd=repo, capture=True)

    section("STEP 4 — Capabilities")
    run(["caps"], cwd=repo, capture=True)

    section("STEP 5 — Coverage")
    run(["cov"], cwd=repo, check=False, capture=True)

    section("STEP 6 — Discover symbol")
    symbol = discover_symbol_with_edges(repo)
    print(f"Chosen symbol: {symbol}")

    section("STEP 7 — Symbol lookup")
    run(["sym", symbol], cwd=repo, capture=True)

    section("STEP 8 — Embeddings")
    run(["emb", "core logic"], cwd=repo, check=False, capture=True)

    section("STEP 9 — Context")
    run(["ctx", "core logic"], cwd=repo, capture=True)

    section("STEP 10 — Context (prompt)")
    run(["ctx", "--prompt", "improve test coverage"], cwd=repo, capture=True)

    section("STEP 11 — Context (json)")
    run(["ctx", "--json", "core logic"], cwd=repo, capture=True)

    section("STEP 12 — Context (explain)")
    run(["ctx", "--explain", "ranking"], cwd=repo, capture=True)

    section("STEP 13 — Calls")
    run(["calls", symbol], cwd=repo, check=False, capture=True)

    section("STEP 14 — Calls tree")
    run(["calls", symbol, "--tree"], cwd=repo, check=False, capture=True)

    section("STEP 15 — Calls dot")
    run(["calls", symbol, "--tree", "--dot"], cwd=repo, check=False, capture=True)

    section("STEP 16 — Calls incoming")
    run(["calls", symbol, "--incoming"], cwd=repo, check=False, capture=True)

    section("STEP 17 — Refs")
    run(["refs", symbol], cwd=repo, check=False, capture=True)

    section("STEP 18 — Refs incoming tree")
    run(["refs", symbol, "--incoming", "--tree"], cwd=repo, check=False, capture=True)

    section("STEP 19 — Refs dot")
    run(["refs", symbol, "--tree", "--dot"], cwd=repo, check=False, capture=True)

    section("STEP 20 — Audit gate")
    ans = input("Does the repo use NumPy docstrings? [y/N]: ").lower()

    if ans == "y":
        section("STEP 21 — Audit")
        run(["audit"], cwd=repo, check=False, capture=True)

        section("STEP 22 — Audit JSON")
        run(["audit", "--json"], cwd=repo, check=False, capture=True)
    else:
        print("Skipping audit (likely noisy)")

    section("DEMO COMPLETE")


if __name__ == "__main__":
    main()
