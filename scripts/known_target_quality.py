"""Validate and score automatic known-target retrieval cases.

Parameters
----------
None

Returns
-------
None
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn, cast

INTENTS = (
    "symbol_lookup",
    "architecture_lookup",
    "task_lookup",
    "docs_lookup",
    "error_or_trace_lookup",
)
SCHEMA_VERSION = "known-target-v1"


@dataclass(frozen=True)
class Target:
    """A source-verified repository location.

    Parameters
    ----------
    path : str
        Repository-relative source path.
    line : int
        Declaration or heading line, or zero for file-level matching.
    kind : str
        Symbol, documentation, or file.

    Returns
    -------
    None
    """

    path: str
    line: int
    kind: str


@dataclass(frozen=True)
class Case:
    """One automatically derived query with verifiable provenance.

    Parameters
    ----------
    id : str
        Stable case identity.
    repo : str
        Manifest repository label.
    commit : str
        Exact source revision.
    intent : str
        Shared query taxonomy category.
    query : str
        Source-derived query text.
    channel : str
        Primary retrieval command.
    targets : tuple[Target, ...]
        Known relevant locations, not exhaustive semantic judgments.
    evidence : dict[str, object]
        Source digest and automatic derivation rule.

    Returns
    -------
    None
    """

    id: str
    repo: str
    commit: str
    intent: str
    query: str
    channel: str
    targets: tuple[Target, ...]
    evidence: dict[str, object]


def invalid(message: str) -> NoReturn:
    """Reject invalid controls or evidence.

    Parameters
    ----------
    message : str
        Diagnostic without source or secret content.

    Returns
    -------
    None
        This function always raises.

    Raises
    ------
    ValueError
        The requested operation cannot be validated.
    """
    raise ValueError(message)


def digest_bytes(value: bytes) -> str:
    """Hash bytes for immutable controls.

    Parameters
    ----------
    value : bytes
        Input bytes.

    Returns
    -------
    str
        SHA-256 digest.
    """
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: object) -> str:
    """Serialize controls deterministically.

    Parameters
    ----------
    value : object
        JSON-compatible data.

    Returns
    -------
    str
        Stable JSON text.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def case_payload(case: Case) -> dict[str, object]:
    """Serialize a case with its version.

    Parameters
    ----------
    case : Case
        Validated case.

    Returns
    -------
    dict[str, object]
        Versioned case record.
    """
    return {"schema_version": SCHEMA_VERSION, **asdict(case)}


def load_target(target: object) -> Target:
    """Validate a canonical source location.

    Parameters
    ----------
    target : object
        Decoded target record.

    Returns
    -------
    Target
        Valid source identity.

    Raises
    ------
    ValueError
        Fields are malformed or the path escapes its repository.
    """
    if not isinstance(target, dict):
        invalid("Invalid target")
    path = target.get("path")
    line = target.get("line")
    kind = target.get("kind")
    if (
        not isinstance(path, str)
        or not path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
        or "\\" in path
        or PurePosixPath(path).as_posix() != path
        or type(line) is not int
        or line < 0
        or kind not in {"symbol", "documentation", "file"}
    ):
        invalid("Invalid target location")
    return Target(path, line, kind)


def load_cases(path: Path) -> tuple[Case, ...]:
    """Validate a versioned dataset without coercing malformed fields.

    Parameters
    ----------
    path : pathlib.Path
        JSONL case file.

    Returns
    -------
    tuple[Case, ...]
        Cases in stable file order.

    Raises
    ------
    ValueError
        A case is malformed, duplicated, or the dataset is empty.
    """
    cases: list[Case] = []
    identities: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get("schema_version") != SCHEMA_VERSION:
            invalid("Unsupported known-target case schema")
        for key in ("id", "repo", "commit", "intent", "query", "channel"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                invalid(f"Invalid case field: {key}")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["id"]) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", row["repo"]
        ):
            invalid("Unsafe case or repository identity")
        if row["id"] in identities:
            invalid(f"Duplicate case: {row['id']}")
        if not re.fullmatch(r"[0-9a-f]{40}", row["commit"]):
            invalid("Cases require exact 40-character revisions")
        if row["intent"] not in INTENTS or row["channel"] not in {"emb", "docs"}:
            invalid("Invalid intent or channel")
        raw_targets = row.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            invalid("A case needs known targets")
        targets = [load_target(target) for target in raw_targets]
        if len(set(targets)) != len(targets):
            invalid("Duplicate known target")
        evidence = row.get("evidence")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("rule"), str):
            invalid("Missing derivation evidence")
        if not isinstance(evidence.get("source_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", evidence["source_sha256"]
        ):
            invalid("Missing source digest")
        identities.add(row["id"])
        cases.append(
            Case(
                row["id"],
                row["repo"],
                row["commit"],
                row["intent"],
                row["query"],
                row["channel"],
                tuple(targets),
                cast("dict[str, object]", evidence),
            )
        )
    if not cases:
        invalid("Dataset contains no cases")
    return tuple(cases)


def ranked_locations(payload: dict[str, object], root: Path) -> tuple[Target, ...]:
    """Read ranked CLI results without promoting nested evidence into ranks.

    Parameters
    ----------
    payload : dict[str, object]
        An emb or docs CLI response.
    root : pathlib.Path
        Repository root for absolute-path normalization.

    Returns
    -------
    tuple[Target, ...]
        Deduplicated locations in returned order.

    Raises
    ------
    ValueError
        The response has no valid ranking envelope or contains invalid rows.
    """
    nested = payload.get("result")
    if isinstance(nested, dict):
        payload = cast("dict[str, object]", nested)
    rows = payload.get("items")
    if rows is None:
        rows = (
            payload.get("top_matches")
            if "top_matches" in payload
            else payload.get("results")
        )
    if payload.get("status") not in {"ok", "no_matches"} or not isinstance(rows, list):
        invalid("Invalid retrieval response")
    ranked: list[Target] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            invalid("Invalid retrieval row")
        path = Path(row["file"])
        if path.is_absolute():
            try:
                path = path.relative_to(root)
            except ValueError:
                invalid("Retrieved path is outside the repository")
        if ".." in path.parts:
            invalid("Retrieved path escapes the repository")
        line = row.get("lineno")
        if type(line) is not int or line < 1:
            invalid("Invalid retrieval line")
        kind = (
            "documentation"
            if payload.get("command") == "docs" or row.get("type") == "documentation"
            else "symbol"
        )
        target = Target(path.as_posix(), line, kind)
        if target not in ranked:
            ranked.append(target)
    return tuple(ranked)


def score_ranking(case: Case, ranking: tuple[Target, ...], k: int) -> dict[str, float]:
    """Measure retrieval of known targets at one cutoff.

    Parameters
    ----------
    case : Case
        Known labels.
    ranking : tuple[Target, ...]
        Ranked locations.
    k : int
        Positive cutoff; missing results count as misses.

    Returns
    -------
    dict[str, float]
        Hit, known-target recall, and reciprocal rank.

    Raises
    ------
    ValueError
        The cutoff is not positive.
    """
    if k < 1:
        invalid("K must be positive")
    found: set[Target] = set()
    first = 0
    for rank, result in enumerate(tuple(dict.fromkeys(ranking))[:k], 1):
        matches = {
            target
            for target in case.targets
            if target.path == result.path
            and (target.line in (0, result.line))
            and (target.kind in ("file", result.kind))
        }
        if matches and not first:
            first = rank
        found.update(matches)
    return {
        "hit": float(bool(found)),
        "recall": len(found) / len(case.targets),
        "mrr": 1.0 / first if first else 0.0,
    }
