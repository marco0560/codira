"""Verify overlapping blockers, profile isolation and unknown closure evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from scripts import analyzer_backlog_catalog as catalog
from scripts.analyzer_backlog_inventory import digest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def originals(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Create three immutable source identities across two repositories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source fixtures.

    Returns
    -------
    dict
        Ledger identities indexed by physical source path.
    """
    result = {}
    for name, repository in [("a", "one"), ("b", "two"), ("c", "one")]:
        path = tmp_path / (name + ".c")
        path.write_text("int " + name + ";\n")
        result[str(path)] = {
            "path": str(path),
            "source_sha256": digest(path),
            "analyzer": "c",
            "repository": repository,
            "relative_path": path.name,
            "repository_revision": "1" * 40,
            "version": "c17",
            "disposition": "investigate_and_fix",
        }
    return result


def test_overlap_and_missing_coverage_prevent_closure_predictions(
    tmp_path: Path,
) -> None:
    """Count each original once per cause and expose independent co-blockers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Immutable source identities.

    Returns
    -------
    None
        One apparent sole blocker remains unknown without the other stages.
    """
    rows = originals(tmp_path)
    a, b, c = rows
    x = ("shared", "product", "confirmed")
    y = ("owner_reference", "reference", "observed")
    facts = [
        catalog.Fact(a, "{}", "root_proof", (x,), False, True, "proof"),
        catalog.Fact(a, "{}", "native", (x,), True, True, "native"),
        catalog.Fact(b, "{}", "native", (x, y), True, True, "native"),
        catalog.Fact(c, "{}", "native", (x,), True, True, "native"),
        catalog.Fact(c, "{}", "parser", (), True, True, "parser"),
        catalog.Fact(c, "{}", "storage", (), True, True, "storage"),
    ]
    report = catalog.rank_blockers(rows, facts, 5)
    shared = next(group for group in report["groups"] if group["id"] == "shared")
    assert shared["files"] == shared["confirmed_files"] == 3
    assert shared["sole_known_blocker_files"] == 2
    assert shared["fully_observed_closure_candidate_files"] == 1
    assert shared["expected_whole_file_closures"] is None
    assert report["qualification_admissions"] == 0
    assert next(row for row in report["files"] if row["path"] == a)[
        "unknown_stages"
    ] == ["parser", "storage"]
    assert catalog.rank_blockers(rows, list(reversed(facts)), 5) == report


def test_profiles_and_historical_producers_never_complete_each_other(
    tmp_path: Path,
) -> None:
    """Keep stale and differently configured stages outside closure coverage.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Source identities.

    Returns
    -------
    None
        Missing-stage evidence stays unknown under both exact profiles.
    """
    rows = originals(tmp_path)
    path = next(iter(rows))
    blocker = (("shared", "product", "confirmed"),)
    facts = [
        catalog.Fact(path, "{}", "native", blocker, True, True, "native"),
        catalog.Fact(
            path,
            '{"include_search_paths": ["include"]}',
            "parser",
            (),
            True,
            True,
            "parser",
        ),
        catalog.Fact(path, "{}", "storage", (), True, False, "historical"),
    ]
    report = catalog.rank_blockers(rows, facts, 5)
    assert report["historical_stage_observations"] == 1
    assert report["originals_without_current_observations"] == 2
    assert report["groups"][0]["fully_observed_closure_candidate_files"] == 0
    assert len(report["files"]) == 2
    conflict = catalog.Fact(path, "{}", "native", (), True, True, "different")
    with pytest.raises(ValueError, match="conflicting current snapshots"):
        catalog.rank_blockers(rows, [*facts, conflict], 5)


def test_observations_reuse_verified_inputs_and_reject_tampering(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Verify source epoch, raw artifact digests and explicit completeness types.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Source, producer and native evidence fixtures.
    monkeypatch : _pytest.monkeypatch.MonkeyPatch
        Active-checkout producer source-set fixture.

    Returns
    -------
    None
        Header/raw-evidence or producer changes cannot silently retain validity.
    """
    rows = originals(tmp_path)
    path = next(iter(rows))
    producer_root = tmp_path / "retained-producer"
    target_root = tmp_path / "active-checkout"
    relative_sources = (
        Path("src/codira/core.py"),
        Path("packages/codira-analyzer-c/src/analyzer.py"),
        Path("packages/codira-analyzer-cpp/src/analyzer.py"),
    )
    for root in (producer_root, target_root):
        for relative in relative_sources:
            source = root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# producer version one\n")

    def hash_sources(root: Path) -> dict[str, str]:
        """Hash Python files in the analyzer producer source roots.

        Parameters
        ----------
        root : pathlib.Path
            Checkout root whose producer files are enumerated.

        Returns
        -------
        dict
            Absolute producer paths and their content digests.
        """
        return {
            str(path): digest(path)
            for prefix in (
                Path("src/codira"),
                Path("packages/codira-analyzer-c/src"),
                Path("packages/codira-analyzer-cpp/src"),
            )
            for path in sorted((root / prefix).rglob("*.py"))
        }

    producer_source_hashes = hash_sources(producer_root)
    monkeypatch.setattr(
        catalog, "producer_hashes", lambda _root: hash_sources(target_root)
    )
    native = tmp_path / "native.json"
    native.write_text("{}\n")
    envelope = {
        "format": "analyzer-blocker-observations-v1",
        "inputs": {str(native): digest(native)},
        "producer_source_hashes": producer_source_hashes,
        "observations": [
            {
                "path": path,
                "source_sha256": rows[path]["source_sha256"],
                "configuration": {},
                "stage": "native",
                "complete": True,
                "blockers": [
                    {
                        "id": "missing_definition",
                        "kind": "product",
                        "confidence": "confirmed",
                    }
                ],
            }
        ],
    }
    observation = tmp_path / "observations.json"
    observation.write_text(json.dumps(envelope))
    assert catalog.observation_facts(observation, rows)[0].current
    (target_root / "packages/codira-analyzer-c/src/analyzer.py").write_text(
        "# target source changed\n"
    )
    assert not catalog.observation_facts(observation, rows)[0].current
    (target_root / "packages/codira-analyzer-c/src/analyzer.py").write_text(
        "# producer version one\n"
    )
    (target_root / "packages/codira-analyzer-c/src/new_module.py").write_text(
        "# target source set grew\n"
    )
    assert not catalog.observation_facts(observation, rows)[0].current
    (target_root / "packages/codira-analyzer-c/src/new_module.py").unlink()
    (producer_root / "src/codira/core.py").write_text("# producer version two\n")
    assert not catalog.observation_facts(observation, rows)[0].current
    envelope["observations"][0]["complete"] = "false"  # type: ignore[index]
    observation.write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match="must be a boolean"):
        catalog.observation_facts(observation, rows)
    native.write_text('{"tampered": true}\n')
    with pytest.raises(ValueError, match="input artifact mismatch"):
        catalog.observation_facts(observation, rows)


def test_empty_evidence_reports_unknowns_without_mutating_ledger(
    tmp_path: Path,
) -> None:
    """Keep unsupported closure estimates unknown even with a small backlog.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated ledger and fresh report identity.

    Returns
    -------
    None
        Every original remains open and an existing report cannot be overwritten.
    """
    rows = originals(tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows.values()))
    before = digest(ledger)
    options = catalog.CatalogOptions(
        ledger, (), (), tmp_path / "catalog", frozenset({"two"})
    )
    report = catalog.build_catalog(options)
    assert (
        report["open_originals"]
        == report["originals_without_current_observations"]
        == 2
    )
    assert report["groups"] == []
    assert report["qualification_admissions"] == 0
    assert digest(ledger) == before
    with pytest.raises(FileExistsError):
        catalog.build_catalog(options)


def test_checkpoint_snapshot_freezes_complete_lines_and_preserves_tail(
    tmp_path: Path,
) -> None:
    """Preserve exact checkpoint bytes while the original writer continues.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source stream and catalog snapshot.

    Returns
    -------
    None
        Joining a live run cannot bind old facts to a later stream digest.
    """
    source = tmp_path / "inventory"
    source.mkdir()
    source.joinpath("inputs.json").write_text("{}\n")
    prefix = b'{"complete": true}\n'
    tail = b'{"unfinished":'
    source.joinpath("results.jsonl").write_bytes(prefix + tail)
    frozen = catalog.snapshot_inventory(source, tmp_path / "snapshot")
    source.joinpath("results.jsonl").write_bytes(prefix + b'{"unfinished": false}\n')
    assert frozen.joinpath("results.jsonl").read_bytes() == prefix
    assert frozen.joinpath("unfinished-tail.raw").read_bytes() == tail
    assert json.loads(frozen.joinpath("origin.json").read_text())[
        "unfinished_tail_bytes"
    ] == len(tail)


def test_identical_independent_witnesses_keep_both_provenance_paths(
    tmp_path: Path,
) -> None:
    """Deduplicate shared blockers without discarding independent evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Immutable source identities.

    Returns
    -------
    None
        Reused observations count one file and retain both proof paths.
    """
    rows = originals(tmp_path)
    path = next(iter(rows))
    blocker = (("shared", "product", "confirmed"),)
    facts = [
        catalog.Fact(path, "{}", "native", blocker, False, True, evidence)
        for evidence in ["first", "second"]
    ]
    report = catalog.rank_blockers(rows, facts, 5)
    assert report["groups"][0]["files"] == 1
    assert report["files"][0]["evidence"] == ["first", "second"]
