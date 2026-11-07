"""Join overlapping analyzer blockers without equating diagnostics with causes.

Run with ``python -m scripts.analyzer_backlog_catalog``. Inventories and native
observation envelopes stay immutable; this command writes a fresh derived view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.analyzer_backlog_inventory import (
    analyzer_for,
    digest,
    json_rows,
    producer_hashes,
    reject,
)


@dataclass(frozen=True)
class Fact:
    """Bind one pipeline-stage observation to a source and exact profile.

    Parameters
    ----------
    path, profile, stage : str
        Original identity, canonical configuration and observed stage.
    blockers : tuple
        Distinct blocker IDs, kinds and confidence labels.
    complete, current : bool
        Exhaustiveness within this stage and producer-source compatibility.
    evidence : str
        Immutable artifact holding the original observation.
    """

    path: str
    profile: str
    stage: str
    blockers: tuple[tuple[str, str, str], ...]
    complete: bool
    current: bool
    evidence: str


@dataclass(frozen=True)
class CatalogOptions:
    """Declare immutable source selections for one derived catalog.

    Parameters
    ----------
    ledger, output : pathlib.Path
        Authoritative classification and fresh report destination.
    inventories, observations : tuple of pathlib.Path
        Existing inventory runs and normalized qualification envelopes.
    excluded : frozenset of str
        Repository labels omitted from this view only.
    samples : int, optional
        Maximum representative paths in each shared blocker group.
    """

    ledger: Path
    inventories: tuple[Path, ...]
    observations: tuple[Path, ...]
    output: Path
    excluded: frozenset[str]
    samples: int = 5


def _relative_producer_hashes(hashes: dict[str, str]) -> dict[str, str] | None:
    """Normalize producer hashes independently of checkout absolute paths.

    Parameters
    ----------
    hashes : dict
        Absolute source paths and retained digests.

    Returns
    -------
    dict or None
        Relative source identities, or None for an unrecognized source set.
    """
    roots = (
        "src/codira/",
        "packages/codira-analyzer-c/src/",
        "packages/codira-analyzer-cpp/src/",
    )
    normalized: dict[str, str] = {}
    for name, expected in hashes.items():
        path = Path(name)
        if not path.is_file() or digest(path) != expected:
            return None
        path_text = path.as_posix()
        relative = next(
            (
                path_text[index:]
                for root in roots
                if (index := path_text.rfind(root)) >= 0
            ),
            None,
        )
        if relative is None or relative in normalized:
            return None
        normalized[relative] = expected
    return normalized


def current_sources(hashes: dict[str, str]) -> bool:
    """Match immutable producer inputs to the active checkout source epoch.

    Parameters
    ----------
    hashes : dict
        Producer checkout source paths and retained digests.

    Returns
    -------
    bool
        True only when producer content, normalized source set and current
        checkout all agree; absolute checkout paths may differ.
    """
    if not hashes:
        return False
    declared = _relative_producer_hashes(hashes)
    if declared is None:
        return False
    target_root = Path(__file__).resolve().parents[1]
    current = _relative_producer_hashes(producer_hashes(target_root))
    return current is not None and declared == current


def inventory_facts(
    directory: Path, originals: dict[str, dict[str, Any]]
) -> list[Fact]:
    """Read source-bound public-analyzer observations and verify DTO artifacts.

    Parameters
    ----------
    directory : pathlib.Path
        Completed or checkpointed inventory directory.
    originals : dict
        Authoritative ledger identities indexed by absolute source path.

    Returns
    -------
    list of Fact
        Readiness and observed diagnostics, never confirmed root causes.
    """
    inputs = json.loads((directory / "inputs.json").read_text())
    if inputs.get("format") != "analyzer-backlog-inventory-v1":
        reject("unsupported inventory format")
    current = current_sources(inputs["source_hashes"])
    facts = []
    for row in json_rows(directory / "results.jsonl"):
        if row["source_sha256"] != originals[row["path"]]["source_sha256"]:
            reject("inventory original identity differs from ledger")
        source = Path(row["path"])
        row_current = (
            current and source.is_file() and digest(source) == row["source_sha256"]
        )
        if row_current and "analysis_input_fingerprint" in row:
            root = source.parents[len(Path(row["relative_path"]).parts) - 1]
            analyzer = analyzer_for(row["analyzer"], row["configuration"])
            row_current = analyzer.analysis_input_fingerprint_matches(
                source, root, row["analysis_input_fingerprint"]
            )
        if (
            "analysis_artifact" in row
            and digest(Path(row["analysis_artifact"])) != row["analysis_sha256"]
        ):
            reject("inventory DTO hash mismatch")
        blockers = []
        if row["state"] == "error":
            blockers.append(
                ("producer_exception:" + str(row["error"]), "product", "observed")
            )
        elif row["state"] == "partial":
            for diagnostic in (row.get("status") or {}).get("diagnostics", []):
                blockers.append(
                    (
                        "diagnostic:"
                        + diagnostic["category"]
                        + ":"
                        + diagnostic["message"],
                        "diagnostic",
                        "observed",
                    )
                )
            if not blockers:
                blockers.append(
                    ("partial_without_diagnostic", "diagnostic", "observed")
                )
        elif row["state"] != "ready":
            reject("unknown inventory state")
        facts.append(
            Fact(
                row["path"],
                json.dumps(row["configuration"], sort_keys=True),
                "parser",
                tuple(sorted(set(blockers))),
                row["state"] == "ready",
                row_current,
                str(directory / "results.jsonl"),
            )
        )
    return facts


def observation_facts(path: Path, originals: dict[str, dict[str, Any]]) -> list[Fact]:
    """Read reusable native, storage or independently proven cause observations.

    Parameters
    ----------
    path : pathlib.Path
        Versioned observation envelope with producer and input digests.
    originals : dict
        Authoritative original identities.

    Returns
    -------
    list of Fact
        Evidence-bound observations with explicit stage and confidence.
    """
    envelope = json.loads(path.read_text())
    if envelope.get("format") != "analyzer-blocker-observations-v1":
        reject("unsupported blocker observation format")
    if not envelope.get("inputs") or any(
        digest(Path(name)) != expected for name, expected in envelope["inputs"].items()
    ):
        reject("observation input artifact mismatch")
    current = current_sources(envelope["producer_source_hashes"])
    facts = []
    for row in envelope["observations"]:
        if row["source_sha256"] != originals[row["path"]]["source_sha256"]:
            reject("observation original identity differs from ledger")
        if type(row["complete"]) is not bool:
            reject("stage completeness must be a boolean")
        if row["stage"] not in {"parser", "native", "storage", "root_proof"}:
            reject("unknown observation stage")
        blockers = []
        for blocker in row["blockers"]:
            if blocker["kind"] not in {
                "product",
                "reference",
                "environment",
                "diagnostic",
            } or blocker["confidence"] not in {"confirmed", "observed", "candidate"}:
                reject("unknown blocker kind or confidence")
            blockers.append((blocker["id"], blocker["kind"], blocker["confidence"]))
        facts.append(
            Fact(
                row["path"],
                json.dumps(row["configuration"], sort_keys=True),
                row["stage"],
                tuple(sorted(set(blockers))),
                row["complete"],
                current
                and Path(row["path"]).is_file()
                and digest(Path(row["path"])) == row["source_sha256"],
                str(path),
            )
        )
    return facts


def release_priority(kind: str, blocker_id: str) -> str:
    """Identify producer failures that obstruct release qualification.

    Parameters
    ----------
    kind : str
        Evidence category assigned to the blocker.
    blocker_id : str
        Stable blocker identifier from the retained observation.

    Returns
    -------
    str
        Producer failure priority or ordinary backlog priority.
    """
    if kind == "product" and blocker_id.startswith("producer_exception:"):
        return "producer_failure"
    return "normal"


def validate_witnesses(previous: list[Fact], current: Fact) -> None:
    """Reject contradictory current observations of the same pipeline stage.

    Parameters
    ----------
    previous : list of Fact
        Retained witnesses for the exact file, configuration and stage.
    current : Fact
        Additional witness being joined.

    Returns
    -------
    None
        Compatible independent witnesses retain their separate provenance.
    """
    if any(
        (fact.blockers, fact.complete) != (current.blockers, current.complete)
        for fact in previous
    ):
        reject("conflicting current snapshots need explicit reconciliation")


def rank_blockers(
    originals: dict[str, dict[str, Any]], facts: list[Fact], samples: int
) -> dict[str, Any]:
    """Rank shared blockers while retaining co-blockers and unknown coverage.

    Parameters
    ----------
    originals : dict
        Open original identities, with language/version/repository labels.
    facts : list of Fact
        Current and historical stage evidence under distinct exact profiles.
    samples : int
        Maximum deterministic representatives per blocker group.

    Returns
    -------
    dict
        Overlapping groups, per-file evidence, coverage and conservative closure
        candidates. Missing native/storage observations prevent closure claims.
    """
    active: dict[tuple[str, str, str], list[Fact]] = defaultdict(list)
    historical = 0
    for fact in facts:
        if fact.path not in originals:
            continue
        if not fact.current:
            historical += 1
            continue
        key = fact.path, fact.profile, fact.stage
        validate_witnesses(active[key], fact)
        active[key].append(fact)
    by_case: dict[tuple[str, str], list[Fact]] = defaultdict(list)
    for witnesses in active.values():
        for fact in witnesses:
            by_case[fact.path, fact.profile].append(fact)
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    files: list[dict[str, Any]] = []
    for (path, profile), observations in sorted(by_case.items()):
        blockers = {blocker for fact in observations for blocker in fact.blockers}
        ids = {blocker[0] for blocker in blockers}
        covered = {fact.stage for fact in observations if fact.complete}
        fully_observed = {"parser", "native", "storage"} <= covered
        files.append(
            {
                "path": path,
                "profile": profile,
                "blocker_ids": sorted(ids),
                "complete_stages": sorted(covered),
                "unknown_stages": sorted({"parser", "native", "storage"} - covered),
                "evidence": sorted({fact.evidence for fact in observations}),
            }
        )
        for blocker_id, kind, confidence in blockers:
            key = profile, blocker_id, kind
            group = groups.setdefault(
                key,
                {
                    "id": blocker_id,
                    "kind": kind,
                    "profile": profile,
                    "paths": set(),
                    "confirmed_paths": set(),
                    "sole_known_blocker_paths": set(),
                    "fully_observed_closure_candidate_paths": set(),
                },
            )
            group["paths"].add(path)
            if confidence == "confirmed":
                group["confirmed_paths"].add(path)
            if len(ids) == 1:
                group["sole_known_blocker_paths"].add(path)
                if fully_observed and kind == "product" and confidence == "confirmed":
                    group["fully_observed_closure_candidate_paths"].add(path)
    ranked = []
    for group in groups.values():
        paths = sorted(group.pop("paths"))
        for field in (
            "confirmed_paths",
            "sole_known_blocker_paths",
            "fully_observed_closure_candidate_paths",
        ):
            group[field.removesuffix("_paths") + "_files"] = len(group.pop(field))
        strata: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for path in paths:
            row = originals[path]
            strata[row["analyzer"], row["version"], row["repository"]].append(path)
        representatives = []
        for stratum in sorted(strata):
            candidates = sorted(
                strata[stratum],
                key=lambda value: hashlib.sha256(
                    (group["id"] + "\0" + value).encode()
                ).hexdigest(),
            )
            representatives.append(candidates[0])
        group.update(
            files=len(paths),
            paths=paths,
            representatives=representatives[:samples],
            language_version_repository=[
                {
                    "language": language,
                    "version": version,
                    "repository": repository,
                    "files": len(members),
                }
                for (language, version, repository), members in sorted(strata.items())
            ],
            expected_whole_file_closures=None,
            release_priority=release_priority(group["kind"], group["id"]),
        )
        ranked.append(group)
    ranked.sort(
        key=lambda row: (
            row["release_priority"] != "producer_failure",
            -row["fully_observed_closure_candidate_files"],
            -row["confirmed_files"],
            -row["sole_known_blocker_files"],
            -row["files"],
            row["id"],
            row["profile"],
            row["kind"],
        )
    )
    observed = {key[0] for key in active}
    return {
        "open_originals": len(originals),
        "originals_with_current_observations": len(observed),
        "originals_without_current_observations": len(set(originals) - observed),
        "historical_stage_observations": historical,
        "groups": ranked,
        "files": files,
        "qualification_admissions": 0,
        "scope": "Overlapping evidence groups. Diagnostics and candidate patterns are not confirmed roots; sole known blockers are not projected closures. Missing pipeline stages remain explicit. Representative paths are deterministic across repository/language-mode strata, not a statistical estimate.",
    }


def snapshot_inventory(directory: Path, destination: Path) -> Path:
    """Freeze a completed-line prefix before joining a live checkpoint stream.

    Parameters
    ----------
    directory : pathlib.Path
        Original inventory, possibly still appending results.
    destination : pathlib.Path
        Fresh snapshot directory inside the derived catalog identity.

    Returns
    -------
    pathlib.Path
        Frozen input directory. Any unfinished trailing bytes remain retained
        separately; source inputs and attempts are never modified.
    """
    destination.mkdir(parents=True, exist_ok=False)
    inputs = (directory / "inputs.json").read_bytes()
    raw = (directory / "results.jsonl").read_bytes()
    end = raw.rfind(b"\n") + 1
    (destination / "inputs.json").open("xb").write(inputs)
    (destination / "results.jsonl").open("xb").write(raw[:end])
    if end != len(raw):
        (destination / "unfinished-tail.raw").open("xb").write(raw[end:])
    origin = {
        "source_directory": str(directory),
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_bytes_sha256": hashlib.sha256(raw).hexdigest(),
        "completed_prefix_sha256": hashlib.sha256(raw[:end]).hexdigest(),
        "unfinished_tail_bytes": len(raw) - end,
    }
    (destination / "origin.json").open("x").write(json.dumps(origin, indent=2) + "\n")
    return destination


def build_catalog(options: CatalogOptions) -> dict[str, Any]:
    """Write a fresh, evidence-hashed backlog census without modifying its ledger.

    Parameters
    ----------
    options : CatalogOptions
        Evidence selections and a fresh output identity.

    Returns
    -------
    dict
        Complete derived report; all absent evidence remains unknown.
    """
    ledger, output = options.ledger, options.output
    inventories, observations = options.inventories, options.observations
    excluded, samples = options.excluded, options.samples
    if samples < 1:
        reject("samples must be positive")
    rows = json_rows(ledger)
    all_originals = {row["path"]: row for row in rows}
    if len(all_originals) != len(rows):
        reject("duplicate original identity")
    originals = {
        path: row
        for path, row in all_originals.items()
        if row["disposition"] == "investigate_and_fix"
        and row["repository"] not in excluded
    }
    output.mkdir(parents=True, exist_ok=False)
    snapshots = tuple(
        snapshot_inventory(directory, output / "evidence" / f"{index:04d}")
        for index, directory in enumerate(inventories)
    )
    facts = [
        fact
        for directory in snapshots
        for fact in inventory_facts(directory, all_originals)
    ]
    facts.extend(
        fact for path in observations for fact in observation_facts(path, all_originals)
    )
    report = rank_blockers(originals, facts, samples)
    groups = Counter(
        (row["analyzer"], row["version"], row["repository"])
        for row in originals.values()
    )
    report["remaining_by_language_version_repository"] = [
        {
            "language": language,
            "version": version,
            "repository": repository,
            "files": count,
        }
        for (language, version, repository), count in sorted(groups.items())
    ]
    inputs = {
        "format": "analyzer-backlog-catalog-v1",
        "ledger_sha256": digest(ledger),
        "driver_sha256": digest(Path(__file__)),
        "excluded_repositories": sorted(excluded),
        "samples": samples,
        "evidence_hashes": {
            str(path): digest(path)
            for path in [
                *observations,
                *(
                    directory / name
                    for directory in snapshots
                    for name in ("inputs.json", "results.jsonl", "origin.json")
                ),
            ]
        },
    }
    (output / "inputs.json").open("x").write(json.dumps(inputs, indent=2) + "\n")
    (output / "facts.jsonl").open("x").write(
        "".join(json.dumps(asdict(fact)) + "\n" for fact in facts)
    )
    (output / "report.json").open("x").write(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    """Build a fresh catalog from retained inventory and qualification evidence.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Emits coverage and group counts, without any ledger admission.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--inventory", action="append", default=[], type=Path)
    parser.add_argument("--observations", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclude-repository", action="append", default=[])
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    options = CatalogOptions(
        args.ledger,
        tuple(args.inventory),
        tuple(args.observations),
        args.output,
        frozenset(args.exclude_repository),
        args.samples,
    )
    report = build_catalog(options)
    print(
        json.dumps(
            {key: value for key, value in report.items() if not isinstance(value, list)}
        )
    )


if __name__ == "__main__":
    main()
