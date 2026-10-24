"""Generate the immutable, stratified Clang frontend pilot cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PILOT_ID = "clang-frontend-pilot-20261024-r1"
SELECTION_SEED = "codira-clang-frontend-20261024-r1"
EXPECTED_LEDGER_SHA256 = (
    "db96d98154254c80820c81ddf2a2f2bd56d7c62104d2f220be40a47de34db101"
)
STRATA = (("llvm", "c"), ("llvm", "cpp"), ("nonllvm", "c"), ("nonllvm", "cpp"))
PER_STRATUM = 50


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSON objects from a newline-delimited JSON file.

    Parameters
    ----------
    path : pathlib.Path
        Input file.

    Returns
    -------
    list of dict
        Parsed rows in source order.
    """
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def evidence_ref(path: Path, root: Path) -> dict[str, str]:
    """Build a path and digest reference for one retained evidence file.

    Parameters
    ----------
    path : pathlib.Path
        Evidence file.
    root : pathlib.Path
        Evidence root used to produce a relative path.

    Returns
    -------
    dict of str
        Relative path and SHA-256 digest.
    """
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}


def family_for(row: dict[str, Any]) -> tuple[str, list[str]]:
    """Assign a broad selection family from recorded source evidence.

    Parameters
    ----------
    row : dict
        Canonical classification row.

    Returns
    -------
    tuple of (str, list of str)
        Family hint and the source fields that triggered it.

    Notes
    -----
    This is a sampling stratum, not a diagnosed root cause. Empty or vague
    classification evidence stays explicitly unclassified.
    """
    evidence = " ".join(
        str(value)
        for field in ("evidence", "feature_notes")
        for value in row.get(field, [])
    )
    evidence = f"{row.get('relative_path', '')} {evidence}".lower()
    families = (
        (
            "preprocessor_context",
            re.compile(
                r"\b(include|header|conditional|ifdef|ifndef|preprocessor|macro)\b"
            ),
        ),
        (
            "declaration_call_template",
            re.compile(r"\b(declaration|call|template|overload|operator|signature)\b"),
        ),
        (
            "grammar_or_language_version",
            re.compile(
                r"\b(grammar|syntax|parser|c\+\+2[0-9]|c2x|c23|constraint|concept)\b"
            ),
        ),
        (
            "harness_or_control",
            re.compile(r"\b(expected-error|verify|fixture|harness|control|test)\b"),
        ),
    )
    for name, pattern in families:
        if pattern.search(evidence):
            matched = [
                field
                for field in ("relative_path", "evidence", "feature_notes")
                if row.get(field)
            ]
            return name, matched
    return "unclassified_open_input", [
        "classification-v79 disposition and source identity"
    ]


def retain_profile(
    profiles: dict[str, dict[str, Any]], source: str, record: dict[str, Any], tier: int
) -> None:
    """Retain the strongest existing profile record for a source.

    Parameters
    ----------
    profiles : dict
        Profile index keyed by normalized absolute source path.
    source : str
        Source path recorded by the profile.
    record : dict
        Captured compile context.
    tier : int
        Lower values represent stronger context evidence.

    Returns
    -------
    None
        Updates `profiles` in place.
    """
    key = str(Path(source).resolve(strict=False))
    current = profiles.get(key)
    if current is None or tier < current["_tier"]:
        record["_tier"] = tier
        profiles[key] = record


def index_compile_database(database: Path, profiles: dict[str, dict[str, Any]]) -> bool:
    """Index commands from one retained compilation database.

    Parameters
    ----------
    database : pathlib.Path
        Existing compilation database.
    profiles : dict
        Destination profile index.

    Returns
    -------
    bool
        Whether the database existed and was indexed.
    """
    if not database.is_file():
        return False
    database_hash = sha256_file(database)
    entries = json.loads(database.read_text(encoding="utf-8"))
    for index, entry in enumerate(entries):
        source = entry.get("file")
        if not source:
            continue
        command = entry.get("command")
        arguments = entry.get("arguments")
        if arguments is None and command:
            try:
                arguments = shlex.split(command)
            except ValueError:
                arguments = None
        retain_profile(
            profiles,
            source,
            {
                "kind": "compile_commands",
                "database_path": str(database),
                "database_sha256": database_hash,
                "command_index": index,
                "directory": entry.get("directory"),
                "command": command,
                "arguments": arguments,
                "output": entry.get("output"),
                "source_file": str(Path(source).resolve(strict=False)),
                "dependency_evidence": None,
            },
            3,
        )
    return True


def load_native_profiles(
    evidence_root: Path, profiles: dict[str, dict[str, Any]]
) -> list[Path]:
    """Index retained native command and dependency records.

    Parameters
    ----------
    evidence_root : pathlib.Path
        Parser-diagnostics evidence root.
    profiles : dict
        Destination profile index.

    Returns
    -------
    list of pathlib.Path
        Existing native profile evidence files read.
    """
    native_root = evidence_root / "native-build-context-r1"
    evidence_paths: list[Path] = []
    dependency_maps: dict[str, dict[str, Any]] = {}
    dependency_paths = (
        native_root / "dependencies-r1/results.jsonl",
        native_root / "dependencies-extra-modes-r1/results.jsonl",
    )
    for dependency_file in dependency_paths:
        if not dependency_file.is_file():
            continue
        evidence_paths.append(dependency_file)
        for record in read_jsonl(dependency_file):
            if record.get("exit") == 0 and record.get("path"):
                record["_evidence_path"] = str(
                    dependency_file.relative_to(evidence_root)
                )
                dependency_maps[str(Path(record["path"]).resolve(strict=False))] = (
                    record
                )

    result_paths = (
        native_root / "artifacts-r1/results.jsonl",
        native_root / "artifacts-extra-modes-r1/results.jsonl",
        native_root / "artifacts-debug-r1/results.jsonl",
        native_root / "syntax-r1/results.jsonl",
        native_root / "syntax-r2/results.jsonl",
    )
    for result_file in result_paths:
        if not result_file.is_file():
            continue
        evidence_paths.append(result_file)
        for record in read_jsonl(result_file):
            source = record.get("path")
            command = record.get("command")
            if not source or not isinstance(command, list):
                continue
            dependency = dependency_maps.get(str(Path(source).resolve(strict=False)))
            dependency_proof = None
            if dependency and dependency.get("command"):
                dependency_proof = {
                    "path": dependency.get("_evidence_path"),
                    "compiler_sha256": dependency.get("compiler_sha256"),
                    "dependency_count": len(dependency.get("dependencies", {})),
                }
            retain_profile(
                profiles,
                source,
                {
                    "kind": "captured_native_profile",
                    "record_path": str(result_file),
                    "record_sha256": sha256_file(result_file),
                    "record_source_sha256": record.get("source_sha256"),
                    "directory": record.get("cwd"),
                    "command": command,
                    "arguments": command,
                    "consumer": record.get("consumer"),
                    "dependency_evidence": dependency_proof,
                },
                1 if dependency_proof else 2,
            )
    return evidence_paths


def load_profile_index(
    evidence_root: Path,
) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    """Index existing compile commands and captured native profile records.

    Parameters
    ----------
    evidence_root : pathlib.Path
        Root holding the retained parser-diagnostics evidence.

    Returns
    -------
    tuple of (dict, list of pathlib.Path)
        Preferred profile by normalized source path and the evidence files read.

    Notes
    -----
    Only existing records are read. The generator never configures a project,
    runs a compiler, or synthesizes command arguments.
    """
    profiles: dict[str, dict[str, Any]] = {}
    evidence_paths: list[Path] = []
    compile_databases = (
        Path(
            "/home/marco/Personalia/Progetti/Software/Python/codira/.artifacts/worktrees/analyzer-c-isl-annotations-r1/.artifacts/c-isl-annotations-r1/native-config-r3/build/compile_commands.json"
        ),
        evidence_root / "llvm-native-config-r1/compile_commands.json",
        evidence_root / "llvm-native-config-r2/compile_commands.json",
        evidence_root
        / "native-llvm-header-build-context-r1/build/compile_commands.json",
    )
    for database in compile_databases:
        if index_compile_database(database, profiles):
            evidence_paths.append(database)
    evidence_paths.extend(load_native_profiles(evidence_root, profiles))
    return profiles, sorted(set(evidence_paths))


def profile_for(
    row: dict[str, Any], profile_index: dict[str, dict[str, Any]], evidence_root: Path
) -> tuple[str, dict[str, Any] | None, list[str]]:
    """Resolve a row's exact retained compile profile, if one exists.

    Parameters
    ----------
    row : dict
        Canonical classification row.
    profile_index : dict
        Existing profile records indexed by source path.
    evidence_root : pathlib.Path
        Root for making evidence references relative.

    Returns
    -------
    tuple
        Context status, profile record, and limitation notes.
    """
    key = str(Path(row["path"]).resolve(strict=False))
    profile = profile_index.get(key)
    if not profile:
        return (
            "no_profile",
            None,
            [
                "No exact retained compile command or dependency proof was found for this translation unit."
            ],
        )
    profile_source_hash = profile.get("record_source_sha256")
    if profile_source_hash is not None and profile_source_hash != row["source_sha256"]:
        return (
            "no_profile",
            None,
            [
                "A retained context record exists but its source digest does not match the canonical row."
            ],
        )
    profile = dict(profile)
    tier = profile.pop("_tier", None)
    profile["record_path"] = (
        str(Path(profile["record_path"]).relative_to(evidence_root))
        if profile.get("record_path")
        else profile.get("record_path")
    )
    profile["source_path_match"] = True
    profile["profile_source_sha256"] = profile_source_hash
    profile["profile_source_sha256_matches"] = (
        profile_source_hash == row["source_sha256"] if profile_source_hash else None
    )
    command_args = profile.get("arguments")
    if isinstance(command_args, list) and command_args:
        profile["original_driver"] = {
            "argv0": command_args[0],
            "basename": Path(command_args[0]).name,
        }
    limitations = []
    if profile.get("dependency_evidence"):
        status = "reproducible_profile"
        limitations.append(
            "Dependency closure is hash-proven; this manifest does not copy header bytes or run a compiler."
        )
    else:
        status = "partial_profile"
        limitations.append(
            "Exact compile arguments are retained, but dependency closure is not hash-proven; generated or included files may still be unavailable."
        )
    profile["profile_rank"] = tier
    return status, profile, limitations


def source_size_band(path: Path) -> str:
    """Classify source size for deterministic complexity balancing.

    Parameters
    ----------
    path : pathlib.Path
        Exact source path.

    Returns
    -------
    str
        One of `small`, `medium`, or `large`.
    """
    size = path.stat().st_size
    return "small" if size < 8192 else "medium" if size < 65536 else "large"


def rank_key(row: dict[str, Any], seed: str) -> str:
    """Return a stable pseudorandom ranking key for a source row.

    Parameters
    ----------
    row : dict
        Cohort candidate.
    seed : str
        Versioned selection seed.

    Returns
    -------
    str
        SHA-256 rank, independent of filesystem enumeration order.
    """
    identity = "\0".join(
        (
            seed,
            row["repository_id"],
            row["repository_relative_path"],
            row["source_sha256"],
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def choose_stratum(
    candidates: list[dict[str, Any]], target: int, seed: str
) -> list[dict[str, Any]]:
    """Select a balanced deterministic sample from one population stratum.

    Parameters
    ----------
    candidates : list of dict
        Candidate rows with family, profile status, and size band fields.
    target : int
        Required sample size.
    seed : str
        Versioned selection seed.

    Returns
    -------
    list of dict
        Selected rows in deterministic selection order.

    Raises
    ------
    ValueError
        If the stratum has fewer candidates than the requested target.

    Notes
    -----
    Round-robin selection across family, profile-context status, size, and
    repository buckets preserves hard/no-context candidates in the denominator.
    """
    if len(candidates) < target:
        message = f"stratum has {len(candidates)} candidates; needs {target}"
        raise ValueError(message)
    buckets: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        bucket = (
            row["feature_family"],
            row["profile_context_status"],
            row["source_size_band"],
            row["repository_id"],
        )
        buckets[bucket].append(row)
    for members in buckets.values():
        members.sort(key=lambda item: rank_key(item, seed))
    keys = sorted(buckets)
    selected: list[dict[str, Any]] = []
    offsets = {key: 0 for key in keys}
    while len(selected) < target:
        made_progress = False
        for key in keys:
            offset = offsets[key]
            if offset < len(buckets[key]):
                selected.append(buckets[key][offset])
                offsets[key] += 1
                made_progress = True
                if len(selected) == target:
                    break
        if not made_progress:
            message = "selection exhausted candidates before reaching target"
            raise ValueError(message)
    return selected


def normalize_overlap_evidence(
    overlap: dict[str, Any] | None,
    source_sha256: str,
    overlap_path: Path,
    evidence_root: Path,
    overlap_sha256: str,
) -> dict[str, Any] | None:
    """Normalize a source-matched overlap record for the cohort row.

    Parameters
    ----------
    overlap : dict or None
        Candidate overlap record for the source path.
    source_sha256 : str
        Canonical source digest that must match the overlap record.
    overlap_path : pathlib.Path
        Evidence file containing the overlap record.
    evidence_root : pathlib.Path
        Root used to render the evidence path in the manifest.
    overlap_sha256 : str
        Digest of the complete overlap evidence file.

    Returns
    -------
    dict or None
        Normalized evidence when the source digests agree.
    """
    if overlap is None or overlap.get("source_sha256") != source_sha256:
        return None
    return {
        "path": str(overlap_path.relative_to(evidence_root)),
        "file_sha256": overlap_sha256,
        "join_status": overlap.get("join_status"),
        "intent_marker_class": overlap.get("intent_marker_class"),
        "benchmark_language": overlap.get("benchmark_language"),
        "parser_error_node_count": overlap.get("parser_error_node_count"),
        "source_sha256_match": True,
    }


def build_manifest(
    ledger: Path, evidence_root: Path, output_dir: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the cohort manifest and a concise context census report.

    Parameters
    ----------
    ledger : pathlib.Path
        Canonical classification v79 JSONL.
    evidence_root : pathlib.Path
        Retained parser-diagnostics evidence root.
    output_dir : pathlib.Path
        Target directory for immutable output artifacts.

    Returns
    -------
    tuple of (dict, dict)
        Manifest and report objects.

    Raises
    ------
    ValueError
        If ledger identity, source identity, or fixed sample cardinality differs.
    """
    digest = sha256_file(ledger)
    if digest != EXPECTED_LEDGER_SHA256:
        message = f"classification ledger SHA mismatch: {digest}"
        raise ValueError(message)
    all_rows = read_jsonl(ledger)
    if len(all_rows) != 25762:
        message = f"classification ledger row count changed: {len(all_rows)}"
        raise ValueError(message)
    profile_index, context_files = load_profile_index(evidence_root)
    overlap_path = (
        evidence_root
        / "parallel-remediation-20261022-r1/llvm-source-intent-census-r1/source-census-r6/candidate-parser-joins.jsonl"
    )
    overlap_rows = read_jsonl(overlap_path)
    overlap_index = {
        str(Path(row["path"]).resolve(strict=False)): row
        for row in overlap_rows
        if row.get("path") and row.get("source_sha256")
    }
    overlap_digest = sha256_file(overlap_path)
    candidate_rows: dict[tuple[str, str], list[dict[str, Any]]] = {
        key: [] for key in STRATA
    }
    source_hash_checks: Counter[str] = Counter()
    for source_row in all_rows:
        if source_row.get("disposition") != "investigate_and_fix" or source_row.get(
            "analyzer"
        ) not in {"c", "cpp"}:
            continue
        language = source_row["analyzer"]
        population = (
            "llvm" if source_row["repository"] == "cpp-llvm-project" else "nonllvm"
        )
        if (population, language) not in candidate_rows:
            continue
        source_path = Path(source_row["path"])
        if not source_path.is_file():
            source_hash_checks["missing"] += 1
            continue
        actual_hash = sha256_file(source_path)
        source_hash_checks[
            "matched" if actual_hash == source_row["source_sha256"] else "mismatched"
        ] += 1
        if actual_hash != source_row["source_sha256"]:
            message = f"source hash mismatch for canonical row {source_row['path']}"
            raise ValueError(message)
        family, family_evidence = family_for(source_row)
        context_status, profile, limitations = profile_for(
            source_row, profile_index, evidence_root
        )
        overlap_evidence = normalize_overlap_evidence(
            overlap_index.get(str(source_path.resolve(strict=False))),
            source_row["source_sha256"],
            overlap_path,
            evidence_root,
            overlap_digest,
        )
        repo_checkout = source_path
        for _ in Path(source_row["relative_path"]).parts:
            repo_checkout = repo_checkout.parent
        row = {
            "population_class": population,
            "language": language,
            "classification_analyzer": language,
            "language_basis": "classification-v79 analyzer field; repository identifier is not used to assign source language",
            "language_mode_evidence": source_row.get("language_mode_evidence", []),
            "all_source_mode_mentions": source_row.get("all_source_mode_mentions", []),
            "harness_run_lines": source_row.get("harness_run_lines", []),
            "repository_id": source_row["repository"],
            "repository_revision": source_row["repository_revision"],
            "repository_checkout": str(repo_checkout),
            "repository_relative_path": source_row["relative_path"],
            "source_path": str(source_path),
            "source_sha256": source_row["source_sha256"],
            "classification_disposition": source_row["disposition"],
            "feature_family": family,
            "family_evidence": {
                "source_fields": family_evidence,
                "classification_evidence": source_row.get("evidence", []),
                "feature_notes": source_row.get("feature_notes", []),
                "interpretation": "sampling hint only; not an adjudicated root cause",
            },
            "overlapping_census_evidence": overlap_evidence,
            "profile_context_status": context_status,
            "profile_availability": "known_command" if profile else "missing_command",
            "dependency_closure_status": (
                "hash_proven"
                if profile and profile.get("dependency_evidence")
                else "not_hash_proven"
            ),
            "original_compile_command": profile,
            "profile_evidence": (
                {
                    "path": profile.get("database_path") or profile.get("record_path"),
                    "sha256": profile.get("database_sha256")
                    or profile.get("record_sha256"),
                    "dependency_evidence": profile.get("dependency_evidence"),
                }
                if profile
                else None
            ),
            "context_limitations": limitations,
            "source_size_bytes": source_path.stat().st_size,
            "source_size_band": source_size_band(source_path),
        }
        candidate_rows[(population, language)].append(row)

    selected: list[dict[str, Any]] = []
    available_counts: dict[str, int] = {}
    for population, language in STRATA:
        key = f"{population}/{language}"
        candidates = candidate_rows[(population, language)]
        available_counts[key] = len(candidates)
        reserved = [row for row in candidates if row.get("overlapping_census_evidence")]
        reserved.sort(key=lambda item: rank_key(item, SELECTION_SEED))
        if population == "llvm":
            desired = {"known_command": 25, "missing_command": 25}
            for availability, target in desired.items():
                fixed = [
                    row
                    for row in reserved
                    if row["profile_availability"] == availability
                ]
                if len(fixed) > target:
                    message = (
                        "reserved control cases exceed a preregistered profile stratum"
                    )
                    raise ValueError(message)
                pool = [
                    row
                    for row in candidates
                    if row["profile_availability"] == availability and row not in fixed
                ]
                selected.extend(fixed)
                selected.extend(
                    choose_stratum(pool, target - len(fixed), SELECTION_SEED)
                )
        else:
            reserved = reserved[:PER_STRATUM]
            remaining = [row for row in candidates if row not in reserved]
            selected.extend(reserved)
            selected.extend(
                choose_stratum(remaining, PER_STRATUM - len(reserved), SELECTION_SEED)
            )
    selected.sort(
        key=lambda row: (
            row["population_class"],
            row["language"],
            row["repository_id"],
            rank_key(row, SELECTION_SEED),
        )
    )
    for index, row in enumerate(selected, start=1):
        row["selection_id"] = f"CFP-{index:03d}"

    repositories: dict[str, dict[str, str]] = {}
    for row in selected:
        repositories.setdefault(
            row["repository_id"],
            {
                "checkout": row["repository_checkout"],
                "pinned_revision": row["repository_revision"],
            },
        )
    evidence_paths = [ledger, *context_files, overlap_path]
    evidence_sources = [
        {"path": str(path), "sha256": sha256_file(path)} for path in evidence_paths
    ]
    counts = Counter((row["population_class"], row["language"]) for row in selected)
    family_counts = Counter(row["feature_family"] for row in selected)
    context_counts = Counter(row["profile_context_status"] for row in selected)
    availability_counts = Counter(row["profile_availability"] for row in selected)
    family_by_stratum = Counter(
        (row["population_class"], row["language"], row["feature_family"])
        for row in selected
    )
    context_by_stratum = Counter(
        (row["population_class"], row["language"], row["profile_context_status"])
        for row in selected
    )
    availability_by_stratum = Counter(
        (row["population_class"], row["language"], row["profile_availability"])
        for row in selected
    )
    drivers = Counter(
        (row.get("original_compile_command") or {})
        .get("original_driver", {})
        .get("basename", "unavailable")
        for row in selected
    )
    size_by_stratum = Counter(
        (row["population_class"], row["language"], row["source_size_band"])
        for row in selected
    )
    manifest = {
        "schema_version": "codira.clang-frontend-pilot-cohort/1",
        "pilot_id": PILOT_ID,
        "manifest_generation": 4,
        "supersedes": "census-r3/cohort-manifest-r3.json (retained unchanged)",
        "selection_seed": SELECTION_SEED,
        "source_snapshot": {
            "path": str(ledger),
            "sha256": digest,
            "row_count": len(all_rows),
            "eligible_open_c_cpp_rows": sum(available_counts.values()),
            "verified_source_hashes": dict(source_hash_checks),
        },
        "selection_method": {
            "description": "Fixed 50-row samples from each LLVM/non-LLVM x C/C++ stratum. Within each LLVM language stratum, select exactly 25 rows with an exact retained compile command and 25 without one; this intentionally oversamples known LLVM profiles and is not a global context-coverage estimate. Preserve every exact open-source join from the retained LLVM parser-error/source-intent census, then balance remaining rows by evidence family, dependency-context status, source size, and repository; order within buckets ranked by SHA-256(seed, repository, path, source hash). Non-LLVM rows retain all known-command cases available under the same balanced selection rules.",
            "family_labels_are_adjudicated_root_causes": False,
            "source_hash_mismatch_policy": "fail closed",
            "context_missing_policy": "retain selected row and hold at measurement time",
            "llvm_known_command_quota_per_language": 25,
            "llvm_missing_command_quota_per_language": 25,
            "known_command_is_dependency_complete": False,
            "known_context_oversampled_not_population_estimate": True,
        },
        "selection_counts": {
            "by_population_language": {
                f"{population}/{language}": counts[(population, language)]
                for population, language in STRATA
            },
            "by_feature_family": dict(sorted(family_counts.items())),
            "by_profile_context_status": dict(sorted(context_counts.items())),
            "by_profile_availability": dict(sorted(availability_counts.items())),
            "by_population_language_family": {
                f"{population}/{language}/{family}": family_by_stratum[
                    (population, language, family)
                ]
                for population, language in STRATA
                for family in sorted(
                    {
                        key[2]
                        for key in family_by_stratum
                        if key[:2] == (population, language)
                    }
                )
            },
            "by_population_language_context": {
                f"{population}/{language}/{status}": context_by_stratum[
                    (population, language, status)
                ]
                for population, language in STRATA
                for status in ("reproducible_profile", "partial_profile", "no_profile")
            },
            "by_population_language_profile_availability": {
                f"{population}/{language}/{status}": availability_by_stratum[
                    (population, language, status)
                ]
                for population, language in STRATA
                for status in ("known_command", "missing_command")
            },
            "original_driver_basename": dict(sorted(drivers.items())),
            "by_population_language_source_size": {
                f"{population}/{language}/{band}": size_by_stratum[
                    (population, language, band)
                ]
                for population, language in STRATA
                for band in ("small", "medium", "large")
            },
            "available_candidates": available_counts,
        },
        "repositories": repositories,
        "evidence_sources": evidence_sources,
        "rows": selected,
    }
    report = {
        "pilot_id": PILOT_ID,
        "manifest_schema": manifest["schema_version"],
        "source_snapshot": manifest["source_snapshot"],
        "selection_counts": manifest["selection_counts"],
        "repository_counts": dict(
            sorted(Counter(row["repository_id"] for row in selected).items())
        ),
        "population_counts": {
            population: {
                "files": sum(row["population_class"] == population for row in selected),
                "languages": dict(
                    sorted(
                        Counter(
                            row["language"]
                            for row in selected
                            if row["population_class"] == population
                        ).items()
                    )
                ),
                "families": dict(
                    sorted(
                        Counter(
                            row["feature_family"]
                            for row in selected
                            if row["population_class"] == population
                        ).items()
                    )
                ),
                "profile_context": dict(
                    sorted(
                        Counter(
                            row["profile_context_status"]
                            for row in selected
                            if row["population_class"] == population
                        ).items()
                    )
                ),
                "profile_availability": dict(
                    sorted(
                        Counter(
                            row["profile_availability"]
                            for row in selected
                            if row["population_class"] == population
                        ).items()
                    )
                ),
            }
            for population in ("llvm", "nonllvm")
        },
        "family_counts_by_population": {
            population: dict(
                sorted(
                    Counter(
                        row["feature_family"]
                        for row in selected
                        if row["population_class"] == population
                    ).items()
                )
            )
            for population in ("llvm", "nonllvm")
        },
        "language_counts_by_population": {
            population: dict(
                sorted(
                    Counter(
                        row["language"]
                        for row in selected
                        if row["population_class"] == population
                    ).items()
                )
            )
            for population in ("llvm", "nonllvm")
        },
        "profile_context_by_population": {
            population: dict(
                sorted(
                    Counter(
                        row["profile_context_status"]
                        for row in selected
                        if row["population_class"] == population
                    ).items()
                )
            )
            for population in ("llvm", "nonllvm")
        },
        "context_by_population_language": {
            f"{population}/{language}": dict(
                sorted(
                    Counter(
                        row["profile_context_status"]
                        for row in selected
                        if (row["population_class"], row["language"])
                        == (population, language)
                    ).items()
                )
            )
            for population, language in STRATA
        },
        "profile_availability_by_population_language": {
            f"{population}/{language}": dict(
                sorted(
                    Counter(
                        row["profile_availability"]
                        for row in selected
                        if (row["population_class"], row["language"])
                        == (population, language)
                    ).items()
                )
            )
            for population, language in STRATA
        },
        "limitations": [
            "Profile context status is based only on exact retained command and dependency evidence; no commands or flags are synthesized.",
            "Compile-database matches without dependency proofs are partial profiles.",
            "LLVM known-command rows are intentionally oversampled at 25 per language stratum and must not be reported as the source population's context-availability rate.",
            "An exact compile command does not prove generated headers or dependency closure are available; those cases can still be held.",
            "A selection family is a balanced sampling hint from recorded text, not a diagnosis of root cause.",
            "The manifest records original compiler commands independently of the Clang syntax-only adaptation produced by the adapter.",
        ],
    }
    return manifest, report


def main(argv: list[str] | None = None) -> int:
    """Generate a versioned cohort manifest and context census report.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments; defaults to process arguments.

    Returns
    -------
    int
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger", type=Path, required=True, help="canonical classification-v79.jsonl"
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        required=True,
        help="retained parser-diagnostics evidence root",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="new immutable cohort output directory",
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(
            f"refusing to overwrite non-empty immutable output directory: {output_dir}"
        )
    manifest, report = build_manifest(args.ledger, args.evidence_root, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "cohort-manifest-r4.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "context-census-r4.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "manifest": str(output_dir / "cohort-manifest-r4.json"),
                "rows": len(manifest["rows"]),
                "counts": manifest["selection_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
