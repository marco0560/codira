"""Capture resumable public-analyzer evidence for an immutable failure ledger.

This inventory measures parser readiness and retains complete DTOs. Native
qualification, storage verification and ledger admission remain separate stages.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import logging
import time
import traceback
import uuid
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from codira_analyzer_c import CAnalyzer
    from codira_analyzer_cpp import CppAnalyzer


@dataclass(frozen=True)
class InventoryCase:
    """Describe one original and one explicit analyzer profile.

    Parameters
    ----------
    ordinal : int
        Stable case number within this run.
    original : dict
        Unmodified ledger row, including immutable source identity.
    profile : str
        Default or explicitly configured profile name.
    configuration : dict
        Exact analyzer options, without inferred language-version claims.
    output : str
        Durable run directory.
    """

    ordinal: int
    original: dict[str, Any]
    profile: str
    configuration: dict[str, object]
    output: str


_ANALYZERS: dict[str, CAnalyzer | CppAnalyzer] = {}
_LOGGER = logging.getLogger(__name__)


def reject(message: str) -> NoReturn:
    """Reject inconsistent inventory evidence.

    Parameters
    ----------
    message : str
        Concrete evidence or input mismatch.

    Returns
    -------
    NoReturn
        Never returns; inconsistent evidence aborts the operation.

    Raises
    ------
    ValueError
        Always; existing run evidence must be preserved.
    """
    raise ValueError(message)


def digest(path: Path) -> str:
    """Return a file digest.

    Parameters
    ----------
    path : pathlib.Path
        Existing immutable input or output.

    Returns
    -------
    str
        SHA-256 hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_rows(path: Path) -> list[dict[str, Any]]:
    """Read heterogeneous external JSON rows at the serialization boundary.

    Parameters
    ----------
    path : pathlib.Path
        JSONL file containing objects.

    Returns
    -------
    list of dict
        Parsed rows; consumers validate their required fields.
    """
    values = [json.loads(line) for line in path.read_text().splitlines() if line]
    if not all(isinstance(value, dict) for value in values):
        reject(f"expected JSON objects: {path}")
    return values


def analyzer_for(
    name: str, configuration: dict[str, object]
) -> CAnalyzer | CppAnalyzer:
    """Reuse a configured analyzer within one worker process.

    Parameters
    ----------
    name : str
        Explicit ledger analyzer, currently C or C++.
    configuration : dict
        Exact options bound to the case.

    Returns
    -------
    CAnalyzer or CppAnalyzer
        Public analyzer instance with stable configuration.
    """
    key = json.dumps([name, configuration], sort_keys=True)
    if key not in _ANALYZERS:
        from codira_analyzer_c import CAnalyzer
        from codira_analyzer_cpp import CppAnalyzer

        if name not in {"c", "cpp"}:
            reject(f"unsupported inventory analyzer: {name}")
        analyzer = CAnalyzer() if name == "c" else CppAnalyzer()
        analyzer.configure(configuration)
        _ANALYZERS[key] = analyzer
    return _ANALYZERS[key]


def make_cases(
    ledger: list[dict[str, Any]],
    profiles: dict[str, Any],
    excluded: set[str],
    output: Path,
) -> list[InventoryCase]:
    """Select open identities and preserve default/configured comparisons.

    Parameters
    ----------
    ledger : list of dict
        Authoritative classification rows.
    profiles : dict
        Repository to analyzer to explicit options mapping.
    excluded : set of str
        Repositories excluded from this measurement, not from remediation.
    output : pathlib.Path
        Immutable run identity.

    Returns
    -------
    list of InventoryCase
        Deterministically ordered cases; no ledger mutation occurs.
    """
    cases: list[InventoryCase] = []
    paths: set[str] = set()
    for row in ledger:
        if row["path"] in paths:
            reject("duplicate original path in ledger")
        paths.add(row["path"])
        if row["disposition"] != "investigate_and_fix" or row["repository"] in excluded:
            continue
        if row["analyzer"] not in {"c", "cpp"}:
            reject("open language needs an explicit inventory adapter")
        configured = profiles.get(row["repository"], {}).get(row["analyzer"], {})
        if not isinstance(configured, dict):
            reject("analyzer profile must be an object")
        for name, options in [("default", {}), ("configured", configured)]:
            if name == "configured" and not options:
                continue
            cases.append(InventoryCase(len(cases) + 1, row, name, options, str(output)))
    return cases


def capture(case: InventoryCase) -> dict[str, Any]:
    """Retain one full DTO, fingerprint and failed-attempt evidence.

    Parameters
    ----------
    case : InventoryCase
        Original source and exact producer profile.

    Returns
    -------
    dict
        Checkpoint row; readiness never means qualified-file success.
    """
    row = case.original
    directory = Path(case.output) / "cases" / f"{case.ordinal:06d}" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    result: dict[str, Any] = {
        key: row[key]
        for key in (
            "path",
            "relative_path",
            "repository",
            "repository_revision",
            "analyzer",
            "source_sha256",
            "version",
        )
    }
    result.update(
        profile=case.profile,
        configuration=case.configuration,
        state="error",
        error=None,
        qualified_files=0,
    )
    started = time.monotonic()
    try:
        path = Path(row["path"])
        relative = Path(row["relative_path"])
        if not path.is_absolute() or relative.is_absolute() or ".." in relative.parts:
            reject("invalid original source coordinates")
        root = path.parents[len(relative.parts) - 1]
        if root / relative != path or digest(path) != row["source_sha256"]:
            reject("immutable original source drift")
        analyzer = analyzer_for(row["analyzer"], case.configuration)
        analyzed = analyzer.analyze_file(path, root)
        result["analysis_seconds"] = time.monotonic() - started
        artifact = directory / "analysis.json"
        artifact.open("x").write(json.dumps(asdict(analyzed), default=str) + "\n")
        result.update(
            analyzer_version=str(analyzer.version),
            state="ready"
            if analyzed.index_symbols and analyzed.status is None
            else "partial",
            analysis_artifact=str(artifact),
            analysis_sha256=digest(artifact),
            configuration_fingerprint=analyzer.configuration_fingerprint,
            analysis_input_fingerprint=analyzer.analysis_input_fingerprint(path, root),
            status=asdict(analyzed.status) if analyzed.status is not None else None,
        )
        if digest(path) != row["source_sha256"]:
            reject("source changed during analysis")
    except Exception as error:
        _LOGGER.exception("Analyzer inventory case failed")
        result.update(state="error", error=f"{type(error).__name__}: {error}")
        (directory / "failure.stderr").open("x").write(traceback.format_exc())
    result["elapsed_seconds"] = time.monotonic() - started
    (directory / "result.json").open("x").write(json.dumps(result, indent=2) + "\n")
    return result


def checkpoint(records: list[dict[str, Any]], selected: int) -> dict[str, object]:
    """Summarize observed cases without promoting readiness to admission.

    Parameters
    ----------
    records : list of dict
        Completed immutable case rows.
    selected : int
        Planned producer-case count.

    Returns
    -------
    dict
        Process counts, profile readiness and zero admissions.
    """
    counts = Counter((row["profile"], row["state"]) for row in records)
    return {
        "processed": len(records),
        "selected": selected,
        "profiles": {
            name: {
                state: counts[name, state] for state in ("ready", "partial", "error")
            }
            for name in sorted({row["profile"] for row in records})
        },
        "originals_observed": len({row["path"] for row in records}),
        "qualified_files": 0,
    }


def producer_hashes(checkout: Path) -> dict[str, str]:
    """Bind public analyzers and core code to the inspected checkout.

    Parameters
    ----------
    checkout : pathlib.Path
        Dedicated source worktree.

    Returns
    -------
    dict
        Exact source-file digests, after rejecting foreign installed analyzers.
    """
    sources = [
        *checkout.glob("src/codira/**/*.py"),
        *checkout.glob("packages/codira-analyzer-c/src/**/*.py"),
        *checkout.glob("packages/codira-analyzer-cpp/src/**/*.py"),
    ]
    for name in ("c", "cpp"):
        module = Path(inspect.getfile(type(analyzer_for(name, {})))).resolve()
        if not module.is_relative_to(checkout):
            reject("installed analyzer comes from another checkout")
    return {str(path): digest(path) for path in sorted(sources)}


def run_inventory(
    ledger: Path,
    profiles_path: Path | None,
    output: Path,
    excluded: set[str],
    workers: int,
) -> dict[str, object]:
    """Run or resume a source-verified inventory with immutable producer inputs.

    Parameters
    ----------
    ledger, profiles_path : pathlib.Path or None
        Classification and optional explicit repository profile mapping.
    output : pathlib.Path
        Fresh run directory, or exactly matching interrupted run.
    excluded : set of str
        Repositories omitted only from this run.
    workers : int
        Positive number of analyzer processes.

    Returns
    -------
    dict
        Terminal inventory summary, without qualification or admission.
    """
    if workers < 1:
        reject("workers must be positive")
    profiles = json.loads(profiles_path.read_text()) if profiles_path else {}
    if not isinstance(profiles, dict):
        reject("profile mapping must be an object")
    output = output.resolve()
    cases = make_cases(json_rows(ledger), profiles, excluded, output)
    checkout = Path(__file__).resolve().parents[1]
    source_hashes = producer_hashes(checkout)
    manifest = {
        "format": "analyzer-backlog-inventory-v1",
        "ledger_sha256": digest(ledger),
        "driver_sha256": digest(Path(__file__)),
        "source_hashes": source_hashes,
        "profiles": profiles,
        "excluded_repositories": sorted(excluded),
        "workers": workers,
        "selected_cases": len(cases),
        "selected_originals": len({case.original["path"] for case in cases}),
        "analyzer_distributions": {
            name: importlib.metadata.version("codira-analyzer-" + name)
            for name in ("c", "cpp")
        },
        "scope": "Public analyzer DTOs under exact profiles. Readiness and diagnostic groups are observations, not proven root causes or file fixes.",
    }
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "inputs.json"
    if inputs.exists():
        if json.loads(inputs.read_text()) != manifest:
            reject("changed run inputs require a fresh immutable identity")
    else:
        inputs.open("x").write(json.dumps(manifest, indent=2) + "\n")
    results = output / "results.jsonl"
    records = json_rows(results) if results.exists() else []
    done = {(row["path"], row["profile"]) for row in records}
    if len(done) != len(records):
        reject("duplicate checkpoint case")
    by_key = {(case.original["path"], case.profile): case for case in cases}
    for row in records:
        case = by_key[row["path"], row["profile"]]
        path = Path(row["path"])
        if (
            digest(path) != row["source_sha256"]
            or row["source_sha256"] != case.original["source_sha256"]
        ):
            reject("completed original drifted; preserve this run")
        if (
            "analysis_artifact" in row
            and digest(Path(row["analysis_artifact"])) != row["analysis_sha256"]
        ):
            reject("completed DTO artifact drifted")
        if "analysis_input_fingerprint" in row:
            root = path.parents[len(Path(row["relative_path"]).parts) - 1]
            analyzer = analyzer_for(row["analyzer"], case.configuration)
            if not analyzer.analysis_input_fingerprint_matches(
                path, root, row["analysis_input_fingerprint"]
            ):
                reject("completed source context drifted; use a fresh identity")
    if (output / "summary.json").exists():
        return dict(json.loads((output / "summary.json").read_text()))
    pending = [
        case for case in cases if (case.original["path"], case.profile) not in done
    ]
    with ProcessPoolExecutor(max_workers=workers) as pool, results.open("a") as stream:
        for future in as_completed([pool.submit(capture, case) for case in pending]):
            row = future.result()
            records.append(row)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            (output / "checkpoint.json").write_text(
                json.dumps(checkpoint(records, len(cases)), indent=2) + "\n"
            )
    if any(digest(Path(path)) != expected for path, expected in source_hashes.items()):
        reject("producer changed during inventory; results remain unqualified")
    summary = checkpoint(records, len(cases))
    summary.update(results_sha256=digest(results), inputs_sha256=digest(inputs))
    (output / "summary.json").open("x").write(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    """Read CLI inputs and report an immutable inventory summary.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Writes source-bound evidence; exits nonzero on invalid run inputs.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude-repository", action="append", default=[])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    print(
        json.dumps(
            run_inventory(
                args.ledger,
                args.profiles,
                args.output,
                set(args.exclude_repository),
                args.workers,
            )
        )
    )


if __name__ == "__main__":
    main()
