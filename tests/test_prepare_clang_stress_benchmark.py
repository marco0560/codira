"""Verify preparation and strict frontend status-gate behavior.

Parameters
----------
None

Returns
-------
None
    Tests assert that preparation is fresh, held by default, and fallback-aware.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tomllib
from pathlib import Path
from typing import cast

import pytest

from scripts import (
    prepare_clang_stress_benchmark as preparation,
    run_test_material_benchmarks as runner,
)

GIT_EXECUTABLE = shutil.which("git") or "/usr/bin/git"


def _sha256(path: Path) -> str:
    """Hash exact file bytes for fixture identities.

    Parameters
    ----------
    path : pathlib.Path
        Fixture file.

    Returns
    -------
    str
        Lowercase SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write deterministic JSON fixture bytes.

    Parameters
    ----------
    path : pathlib.Path
        Destination path.
    value : object
        JSON-serializable value.

    Returns
    -------
    None
        The JSON document is written to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _worktree(root: Path) -> None:
    """Initialize a small committed Git checkout for worktree binding.

    Parameters
    ----------
    root : pathlib.Path
        New temporary repository root.

    Returns
    -------
    None
        A valid Git HEAD and benchmark runner file are created.
    """
    root.mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "scripts/run_test_material_benchmarks.py").write_text(
        "# test runner\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "add",
            "scripts",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )


def _source_inputs(root: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    """Create a source manifest plus its exact immutable config identity.

    Parameters
    ----------
    root : pathlib.Path
        Temporary source input root.

    Returns
    -------
    tuple[pathlib.Path, pathlib.Path, pathlib.Path, dict[str, object]]
        Manifest path, corpus repository, config path, and manifest value.
    """
    run = root / "original-run"
    config = run / "configs/profile/repo.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        '[embeddings]\nenabled = true\nengine = "onnx"\n'
        '[plugins]\n[plugins.analyzer-c]\nfrontend = "tree-sitter"\n',
        encoding="utf-8",
    )
    corpus = root / "corpus"
    corpus.mkdir()
    (corpus / "unit.c").write_text("int unit(void) { return 0; }\n", encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "init", "-q", str(corpus)], check=True)
    subprocess.run([GIT_EXECUTABLE, "-C", str(corpus), "add", "unit.c"], check=True)
    subprocess.run(
        [
            GIT_EXECUTABLE,
            "-C",
            str(corpus),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    revision = subprocess.check_output(
        [GIT_EXECUTABLE, "-C", str(corpus), "rev-parse", "HEAD"], text=True
    ).strip()
    manifest: dict[str, object] = {
        "schema_version": 1,
        "name": "frozen-source",
        "codira_root": "/historical/worktree",
        "artifact_root": "/historical/artifacts",
        "profiles": [{"id": "sqlite-onnx", "backend": "sqlite", "embeddings": True}],
        "repositories": [
            {
                "label": "c-fixture",
                "path": str(corpus),
                "revision": revision,
                "analyzer_loc": {"c": 10, "cpp": 0},
                "configs": {"sqlite-onnx": "configs/profile/repo.toml"},
            }
        ],
    }
    manifest_path = run / "manifest.json"
    _write_json(manifest_path, manifest)
    _write_json(
        run / "identity.json",
        {
            "manifest_sha256": _sha256(manifest_path),
            "configs": {"configs/profile/repo.toml": _sha256(config)},
        },
    )
    return manifest_path, corpus, config, manifest


def _context_selection(
    path: Path, manifest: dict[str, object], manifest_path: Path, corpus: Path
) -> Path:
    """Create one exact compile database selection with helper bindings.

    Parameters
    ----------
    path : pathlib.Path
        Context selection output.
    manifest : dict[str, object]
        Frozen source manifest.
    manifest_path : pathlib.Path
        Exact source manifest.
    corpus : pathlib.Path
        Repository fixture containing one C translation unit.

    Returns
    -------
    pathlib.Path
        Context selection path.
    """
    source = corpus / "unit.c"
    build = path.parent / "build"
    build.mkdir(parents=True)
    database = build / "compile_commands.json"
    _write_json(
        database,
        [
            {
                "directory": str(build),
                "file": str(source),
                "arguments": ["clang", "-c", str(source)],
            }
        ],
    )
    helper = build / "clang-helper"
    helper.write_bytes(b"helper fixture")
    receipt = build / "build-receipt.json"
    _write_json(receipt, {"helper_sha256": _sha256(helper)})
    context = {
        "schema": preparation.CONTEXT_SCHEMA,
        "source_manifest_sha256": _sha256(manifest_path),
        "helper": {"path": str(helper), "sha256": _sha256(helper)},
        "build_receipt": {"path": str(receipt), "sha256": _sha256(receipt)},
        "contexts": [
            {
                "repository": cast(
                    "str",
                    cast("list[dict[str, object]]", manifest["repositories"])[0][
                        "label"
                    ],
                ),
                "language": "c",
                "kind": "compile_commands",
                "evidence": {"path": str(database), "sha256": _sha256(database)},
            }
        ],
    }
    _write_json(path, context)
    return path


def test_prepare_is_fresh_clang_draft_and_reports_missing_contexts(
    tmp_path: Path,
) -> None:
    """Keep the draft non-runnable when no compiler context is selected.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.

    Returns
    -------
    None
        The draft sets Clang explicitly and records held coverage.
    """
    worktree = tmp_path / "worktree"
    _worktree(worktree)
    manifest_path, _corpus, original_config, _manifest = _source_inputs(tmp_path)

    output = worktree / ".artifacts/analysis/prep-r1"
    plan = preparation.prepare(manifest_path, worktree, output, None, "preserve")

    assert plan["launch_eligible"] is False
    assert plan["benchmark_launched"] is False
    assert plan["tree_sitter_fallback_counted_as_clang"] is False
    assert "native helper path and digest are not supplied" in cast(
        "list[str]", plan["blocking_reasons"]
    )
    assert (
        original_config.read_text(encoding="utf-8").find('frontend = "tree-sitter"')
        >= 0
    )
    assert not (output / "manifest.json").exists()
    draft = json.loads((output / "manifest.draft.json").read_text(encoding="utf-8"))
    repositories = cast("list[dict[str, object]]", draft["repositories"])
    configs = cast("dict[str, str]", repositories[0]["configs"])
    assert draft["require_clang_frontend_status"] is True
    assert draft["codira_root"] == str(worktree)
    config = tomllib.loads((output / configs["sqlite-onnx"]).read_text())
    assert config["plugins"]["analyzer-c"]["frontend"] == "clang"


def test_prepare_counts_exact_compile_rows_but_holds_partial_context(
    tmp_path: Path,
) -> None:
    """Select exact CDB rows but keep argv-only evidence held.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.

    Returns
    -------
    None
        The translation-unit match is counted, but missing guards keep it held.
    """
    worktree = tmp_path / "worktree"
    _worktree(worktree)
    manifest_path, corpus, _original_config, manifest = _source_inputs(tmp_path)
    contexts = _context_selection(
        tmp_path / "contexts.json", manifest, manifest_path, corpus
    )
    output = worktree / ".artifacts/analysis/prep-r1"

    plan = preparation.prepare(manifest_path, worktree, output, contexts, "preserve")

    contexts_summary = cast("dict[str, dict[str, dict[str, object]]]", plan["contexts"])
    context_summary = contexts_summary["c-fixture"]["c"]
    assert context_summary["state"] == "held"
    assert context_summary["covered_translation_unit_count"] == 1
    assert any(
        "guarded Clang profiles are unavailable" in item
        for item in cast("list[str]", context_summary["failures"])
    )
    assert plan["launch_eligible"] is False
    assert not any(
        "c-fixture/c context held" in item
        for item in cast("list[str]", plan["blocking_reasons"])
    )
    assert any(
        "native Clang toolchain validation failed" in item
        for item in cast("list[str]", plan["blocking_reasons"])
    )
    draft = json.loads((output / "manifest.draft.json").read_text(encoding="utf-8"))
    repositories = cast("list[dict[str, object]]", draft["repositories"])
    configs = cast("dict[str, str]", repositories[0]["configs"])
    config = tomllib.loads((output / configs["sqlite-onnx"]).read_text())
    assert config["plugins"]["analyzer-c"]["frontend"] == "clang"
    assert "clang_compile_commands" in config["plugins"]["analyzer-c"]


def test_prepare_allows_held_contexts_when_toolchain_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep missing profile coverage visible without blocking the full run.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable preparation root.
    monkeypatch : pytest.MonkeyPatch
        Supplies a validated global toolchain identity for the fixture helper.

    Returns
    -------
    None
        Partial source coverage is launchable and remains explicitly held.
    """
    worktree = tmp_path / "worktree"
    _worktree(worktree)
    manifest_path, corpus, _original_config, manifest = _source_inputs(tmp_path)
    contexts = _context_selection(
        tmp_path / "contexts.json", manifest, manifest_path, corpus
    )
    monkeypatch.setattr(
        preparation,
        "_validate_global_helper",
        lambda _context: (
            {
                "helper_path": "/fixture/clang-helper",
                "helper_sha256": "a" * 64,
                "build_receipt_path": "/fixture/build-receipt.json",
                "build_receipt_sha256": "b" * 64,
                "compiler_path": "/fixture/clang",
                "compiler_sha256": "c" * 64,
                "compiler_version": "fixture clang",
                "resource_dir": "/fixture/resource",
                "resource_probe_sha256": "d" * 64,
                "frontend_package_version": "fixture",
            },
            [],
        ),
    )

    output = worktree / ".artifacts/analysis/prep-held-run"
    plan = preparation.prepare(manifest_path, worktree, output, contexts, "preserve")

    summary = cast("dict[str, dict[str, dict[str, object]]]", plan["contexts"])
    source_context = summary["c-fixture"]["c"]
    assert plan["launch_eligible"] is True
    assert source_context["state"] == "held"
    assert source_context["held_translation_units"] == [
        {
            "path": str(corpus / "unit.c"),
            "reason": "only argv is captured; guarded profile is unavailable",
        }
    ]
    assert plan["embedding_policy"] == "preserve"
    draft = json.loads((output / "manifest.draft.json").read_text(encoding="utf-8"))
    assert draft["clang_external_inputs"]["c-fixture"]["c"]
    assert draft["clang_toolchain"]["compiler_version"] == "fixture clang"


def test_changed_manifest_requires_explicit_new_input_identity(tmp_path: Path) -> None:
    """Record manifest drift as a new input only after an explicit acknowledgement.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.

    Returns
    -------
    None
        An acknowledged new input is bound separately from its old identity.
    """
    worktree = tmp_path / "worktree"
    _worktree(worktree)
    manifest_path, corpus, _original_config, manifest = _source_inputs(tmp_path)
    original_bytes = manifest_path.read_bytes()
    historical_sha = hashlib.sha256(original_bytes).hexdigest()
    manifest_path.write_bytes(original_bytes + b" ")
    contexts = _context_selection(
        tmp_path / "contexts.json", manifest, manifest_path, corpus
    )
    with pytest.raises(preparation.PreparationError):
        preparation.prepare(
            manifest_path,
            worktree,
            worktree / ".artifacts/analysis/unacknowledged",
            contexts,
            "preserve",
        )
    selection = json.loads(contexts.read_text(encoding="utf-8"))
    selection["source_manifest_mismatch_ack"] = "accept_current_bytes_as_new_input"
    _write_json(contexts, selection)

    output = worktree / ".artifacts/analysis/prep-new-input"
    plan = preparation.prepare(manifest_path, worktree, output, contexts, "preserve")

    assert plan["source_manifest_identity_matches"] is False
    assert plan["source_manifest_treated_as_new_input"] is True
    assert plan["source_manifest_sha256"] == _sha256(manifest_path)
    assert plan["historical_identity_manifest_sha256"] == historical_sha
    assert plan["historical_identity_manifest_sha256"] != plan["source_manifest_sha256"]
    draft = json.loads((output / "manifest.draft.json").read_text(encoding="utf-8"))
    assert draft["name"] == "clang-full-stress-prep-new-input"
    assert draft["source_campaign_name"] == "frozen-source"


def test_manifest_selected_config_must_be_identity_bound_and_contained(
    tmp_path: Path,
) -> None:
    """Reject config paths missing from identity or escaping their source root.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        Both an unbound config and an escaping identity key fail before copying.
    """
    worktree = tmp_path / "worktree"
    _worktree(worktree)
    manifest_path, corpus, _config, manifest = _source_inputs(tmp_path)
    original_repo = cast("list[dict[str, object]]", manifest["repositories"])[0]
    original_config = cast("dict[str, str]", original_repo["configs"])["sqlite-onnx"]
    identity_path = manifest_path.with_name("identity.json")
    identity = json.loads(identity_path.read_text(encoding="utf-8"))

    cast("dict[str, str]", original_repo["configs"])["sqlite-onnx"] = "../outside.toml"
    _write_json(manifest_path, manifest)
    contexts = _context_selection(
        tmp_path / "contexts.json", manifest, manifest_path, corpus
    )
    selection = json.loads(contexts.read_text(encoding="utf-8"))
    selection["source_manifest_mismatch_ack"] = "accept_current_bytes_as_new_input"
    _write_json(contexts, selection)
    with pytest.raises(
        preparation.PreparationError, match="not bound by source identity"
    ):
        preparation.prepare(
            manifest_path,
            worktree,
            worktree / ".artifacts/analysis/unbound-config",
            contexts,
            "preserve",
        )

    outside = tmp_path / "outside.toml"
    outside.write_text("[fixture]\n", encoding="utf-8")
    identity["configs"]["../outside.toml"] = _sha256(outside)
    identity["configs"].pop(original_config)
    _write_json(identity_path, identity)
    with pytest.raises(preparation.PreparationError, match="must be inside"):
        preparation.prepare(
            manifest_path,
            worktree,
            worktree / ".artifacts/analysis/escaping-config",
            contexts,
            "preserve",
        )


def test_status_gate_accounts_tree_sitter_as_held_not_clang(tmp_path: Path) -> None:
    """Keep a persisted Tree-sitter fallback held and outside Clang counts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.

    Returns
    -------
    None
        The fallback is per-file held while the audit remains usable.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    source = repository / "unit.c"
    source.write_text("int unit;\n", encoding="utf-8")
    source_sha = _sha256(source)
    database = tmp_path / "index.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE files(path TEXT, hash TEXT, analyzer_name TEXT);"
        "CREATE TABLE analysis_status(path TEXT, grammar TEXT, target_contract TEXT, "
        "coverage_state TEXT, omitted_categories TEXT);"
    )
    connection.execute(
        "INSERT INTO files VALUES (?, ?, ?)", (str(source), source_sha, "c")
    )
    connection.execute(
        "INSERT INTO analysis_status VALUES (?, ?, ?, ?, ?)",
        (
            str(source),
            "tree-sitter-c",
            json.dumps(
                {
                    "language": "c",
                    "requested_frontend": "clang",
                    "selected_frontend": "tree-sitter",
                }
            ),
            "partial",
            "[]",
        ),
    )
    connection.commit()
    connection.close()

    audit = runner.audit_clang_frontend_database(
        database,
        "sqlite",
        repository,
        {source: source_sha},
        {source: "sha256:compile-profile"},
    )

    assert audit["passed"] is True
    assert audit["coverage_complete"] is False
    assert audit["tree_sitter_fallback_count"] == 1
    assert audit["clang_proven_count"] == 0
    assert audit["held_source_count"] == 1
    assert audit["held_sources"] == [
        {"path": str(source), "reason": "Tree-sitter fallback"}
    ]
    stale_hash = runner.audit_clang_frontend_database(
        database, "sqlite", repository, {source: "0" * 64}
    )
    assert stale_hash["passed"] is False
    assert stale_hash["failures"] == [
        {"path": str(source), "reason": "persisted source hash differs"}
    ]


def test_status_gate_accounts_absent_files_as_per_file_holds(tmp_path: Path) -> None:
    """Report missing persisted paths as held while preserving exact inventory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary path root.

    Returns
    -------
    None
        Missing database rows cannot be counted as Clang but do not block the
        other measurements when database access and source identity are sound.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    source = repository / "absent.c"
    source.write_text("int absent;\n", encoding="utf-8")
    database = tmp_path / "index.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE files(path TEXT, hash TEXT, analyzer_name TEXT);"
        "CREATE TABLE analysis_status(path TEXT, grammar TEXT, target_contract TEXT, "
        "coverage_state TEXT, omitted_categories TEXT);"
    )
    connection.commit()
    connection.close()

    audit = runner.audit_clang_frontend_database(
        database, "sqlite", repository, {source: _sha256(source)}
    )

    assert audit["passed"] is True
    assert audit["clang_proven_count"] == 0
    assert audit["held_sources"] == [
        {"path": str(source), "reason": "no persisted file row"}
    ]


def test_status_gate_accepts_only_complete_source_bound_clang_status(
    tmp_path: Path,
) -> None:
    """Require exact file hashes and positive Clang profile bindings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Pytest temporary root.

    Returns
    -------
    None
        A complete persisted Clang row is accepted.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    source = repository / "unit.c"
    source.write_text("int unit;\n", encoding="utf-8")
    source_sha = _sha256(source)
    database = tmp_path / "index.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        "CREATE TABLE files(path TEXT, hash TEXT, analyzer_name TEXT);"
        "CREATE TABLE analysis_status(path TEXT, grammar TEXT, target_contract TEXT, "
        "coverage_state TEXT, omitted_categories TEXT);"
    )
    target_contract = {
        "language": "c",
        "frontend": "clang",
        "requested_source_path": str(source),
        "requested_source_sha256": source_sha,
        "profile_identity": "sha256:compile-profile",
        "compilation_context": {"target_triple": "x86_64-unknown-linux-gnu"},
    }
    connection.execute(
        "INSERT INTO files VALUES (?, ?, ?)", (str(source), source_sha, "c")
    )
    connection.execute(
        "INSERT INTO analysis_status VALUES (?, ?, ?, ?, ?)",
        (
            str(source),
            "clang-c-frontend",
            json.dumps(target_contract),
            "complete",
            "[]",
        ),
    )
    connection.commit()
    connection.close()

    audit = runner.audit_clang_frontend_database(
        database,
        "sqlite",
        repository,
        {source: source_sha},
        {source: "sha256:compile-profile"},
    )

    assert audit["passed"] is True
    assert audit["coverage_complete"] is True
    assert audit["clang_proven_count"] == 1
    assert audit["tree_sitter_fallback_count"] == 0
    mismatched = runner.audit_clang_frontend_database(
        database,
        "sqlite",
        repository,
        {source: source_sha},
        {source: "sha256:other-profile"},
    )
    assert mismatched["passed"] is True
    assert mismatched["clang_proven_count"] == 0
    assert mismatched["held_sources"] == [
        {
            "path": str(source),
            "reason": "persisted profile identity differs from selected profile",
        }
    ]


def test_clang_external_input_mutation_breaks_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind external CDB/helper bytes and reject changes before resume.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable path root.
    monkeypatch : pytest.MonkeyPatch
        Supplies a deterministic frontend identity implementation.

    Returns
    -------
    None
        Exact inputs validate, and changing any bound file is rejected.
    """
    import sys
    import types
    from types import SimpleNamespace

    external_root = tmp_path / "external"
    external_root.mkdir()
    cdb = external_root / "compile_commands.json"
    helper = external_root / "clang-helper"
    receipt = external_root / "build-receipt.json"
    cdb.write_text("[]", encoding="utf-8")
    helper.write_bytes(b"helper")
    receipt.write_text("{}", encoding="utf-8")
    expected_toolchain = {
        "helper_path": str(helper.resolve()),
        "helper_sha256": _sha256(helper),
        "build_receipt_path": str(receipt.resolve()),
        "build_receipt_sha256": _sha256(receipt),
        "compiler_path": str(external_root / "clang"),
        "compiler_sha256": "a" * 64,
        "compiler_version": "clang test",
        "resource_dir": str(external_root / "resource"),
        "resource_probe_sha256": "b" * 64,
        "frontend_package_version": "test-version",
    }

    class FakeFrontend:
        """Supply the bound helper identity without invoking native Clang."""

        def __init__(self, _helper: Path, _receipt: Path, *, package_version: str):
            assert package_version == "test-version"

        def _load_toolchain_identity(self) -> SimpleNamespace:
            return SimpleNamespace(
                helper_path=Path(expected_toolchain["helper_path"]),
                helper_sha256=expected_toolchain["helper_sha256"],
                build_receipt_path=Path(expected_toolchain["build_receipt_path"]),
                build_receipt_sha256=expected_toolchain["build_receipt_sha256"],
                compiler_path=Path(expected_toolchain["compiler_path"]),
                compiler_sha256=expected_toolchain["compiler_sha256"],
                compiler_version=expected_toolchain["compiler_version"],
                resource_dir=Path(expected_toolchain["resource_dir"]),
                resource_probe_sha256=expected_toolchain["resource_probe_sha256"],
                package_version=expected_toolchain["frontend_package_version"],
            )

    fake_module = types.ModuleType("codira_clang_frontend")
    fake_module.__dict__.update(
        {"ClangFrontend": FakeFrontend, "__version__": "test-version"}
    )
    monkeypatch.setitem(sys.modules, "codira_clang_frontend", fake_module)
    spec = {
        "require_clang_frontend_status": True,
        "clang_toolchain": expected_toolchain,
        "clang_external_inputs": {
            "fixture": {
                "c": [
                    {"path": str(path.resolve()), "sha256": _sha256(path)}
                    for path in (cdb, helper, receipt)
                ]
            }
        },
    }

    assert runner.verify_clang_external_inputs(spec) == expected_toolchain
    cdb.write_text('[{"changed":true}]', encoding="utf-8")
    with pytest.raises(ValueError, match="external input changed"):
        runner.verify_clang_external_inputs(spec)


def test_verify_revisions_rejects_untracked_corpus_sources(tmp_path: Path) -> None:
    """Reject untracked files that could enter source indexing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository root.

    Returns
    -------
    None
        The pinned clean checkout passes; an untracked file fails verification.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    subprocess.run([GIT_EXECUTABLE, "init", str(repository)], check=True)
    subprocess.run(
        [GIT_EXECUTABLE, "-C", str(repository), "config", "user.name", "Fixture"],
        check=True,
    )
    subprocess.run(
        [
            GIT_EXECUTABLE,
            "-C",
            str(repository),
            "config",
            "user.email",
            "fixture@example.invalid",
        ],
        check=True,
    )
    source = repository / "unit.c"
    source.write_text("int unit;\n", encoding="utf-8")
    subprocess.run([GIT_EXECUTABLE, "-C", str(repository), "add", "unit.c"], check=True)
    subprocess.run(
        [GIT_EXECUTABLE, "-C", str(repository), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
        text=True,
    )
    spec = {
        "repositories": [
            {
                "label": "fixture",
                "path": str(repository),
                "revision": subprocess.check_output(
                    [GIT_EXECUTABLE, "-C", str(repository), "rev-parse", "HEAD"],
                    text=True,
                ).strip(),
            }
        ]
    }

    runner.verify_revisions(spec)
    (repository / "new.c").write_text("int added;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dirty or untracked"):
        runner.verify_revisions(spec)
    assert runner.post_run_integrity_result(spec) is not None


def test_campaign_clang_gate_marks_held_rows_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the actual campaign gate and preserve held coverage in its result.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable gate state directory.
    monkeypatch : pytest.MonkeyPatch
        Supplies deterministic source inventory and persisted audit results.

    Returns
    -------
    None
        Held rows remain queryable but cannot be reported as complete Clang.
    """
    source = tmp_path / "unit.c"
    source.write_text("int unit;\n", encoding="utf-8")
    held = [{"path": str(source), "reason": "Tree-sitter fallback"}]
    monkeypatch.setattr(
        runner,
        "_clang_source_hash_inventory",
        lambda _repo, _loc: ({source: _sha256(source)}, [], [], []),
    )
    monkeypatch.setattr(
        runner,
        "audit_clang_frontend_database",
        lambda *_args: {
            "passed": True,
            "held_source_count": 1,
            "held_sources": held,
            "clang_proven_count": 0,
        },
    )
    campaign = runner.Campaign.__new__(runner.Campaign)
    campaign.spec = {"require_clang_frontend_status": True}
    campaign.root = tmp_path / "run"
    campaign.root.mkdir()
    monkeypatch.setattr(campaign, "exclude_queries", lambda *_args: None)
    indexed = {"status": "passed", "usable": True}

    assert campaign.gate_clang_frontend_status(
        indexed,
        {"label": "fixture", "path": str(tmp_path), "analyzer_loc": {"c": 1}},
        {"backend": "sqlite"},
        tmp_path,
        "fixture/index",
    )
    assert indexed["status"] == "partial"
    assert indexed["comparison_group"] == "partial_coverage"
    assert indexed["clang_held_sources"] == held


def test_source_inventory_holds_file_symlinks_outside_repository(
    tmp_path: Path,
) -> None:
    """Exclude source and header symlinks that leave the pinned checkout.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        Outside targets are reported as held and never inventoried.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    outside_source = tmp_path / "outside.c"
    outside_source.write_text("int outside;\n", encoding="utf-8")
    source_link = repository / "link.c"
    source_link.symlink_to(outside_source)
    outside_header = tmp_path / "outside.h"
    outside_header.write_text("int outside_header;\n", encoding="utf-8")
    header_link = repository / "link.h"
    header_link.symlink_to(outside_header)

    sources, headers, directories, held_files = preparation._scan_source_inventory(
        repository, "c"
    )

    assert sources == []
    assert headers == []
    assert directories == []
    assert held_files == [
        {
            "path": str(header_link),
            "target": str(outside_header),
            "outside_repository": True,
        },
        {
            "path": str(source_link),
            "target": str(outside_source),
            "outside_repository": True,
        },
    ]


def test_clang_hash_inventory_holds_file_symlink_outside_repository(
    tmp_path: Path,
) -> None:
    """Keep escaped file links out of runtime Clang hash inventories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fixture root.

    Returns
    -------
    None
        The escaping target is held without reading or hashing its bytes.
    """
    repository = tmp_path / "corpus"
    repository.mkdir()
    outside_source = tmp_path / "outside.c"
    outside_source.write_text("int outside;\n", encoding="utf-8")
    source_link = repository / "link.c"
    source_link.symlink_to(outside_source)

    hashes, directories, held_files, failures = runner._clang_source_hash_inventory(
        repository, {"c": 1}
    )

    assert hashes == {}
    assert directories == []
    assert held_files == [
        {
            "path": str(source_link),
            "target": str(outside_source),
            "outside_repository": True,
        }
    ]
    assert failures == []
