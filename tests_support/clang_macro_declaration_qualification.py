"""Support source-bound native and persisted Clang macro qualification.

Parameters
----------
None

Returns
-------
None
    This module supplies test fixtures and evidence-validation helpers.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from codira.config import override_repo_config_path
from codira.indexer import index_repo
from codira.mcp.adapter import MCPAdapter
from codira.storage import override_storage_root

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/clang-macro-declaration-qualification-20261028-r1"
EXPECTED_HELPER_SHA256 = (
    "af62dc2f29c13074a5ee068ed1808ee8e0a235dcb209d7aab2f27129de2b6234"
)
EXPECTED_BUILD_RECEIPT_SHA256 = (
    "7f260ba1161a5eb04f7e2571881cd1ad2638d13224b5a2a64bd0554b34d78009"
)


@dataclass(frozen=True)
class NativeQualificationCase:
    """One durable source and prepared native profile.

    Parameters
    ----------
    language : str
        Analyzer language selected for this source.
    root : pathlib.Path
        Durable isolated source-repository root.
    source : pathlib.Path
        Source file whose bytes are bound by the profile.
    profile : pathlib.Path
        Complete captured-profile JSON path.
    helper : pathlib.Path
        Manifest-selected native helper binary.
    build_receipt : pathlib.Path
        Helper build receipt bound to the selected binary.
    capture : dict[str, object]
        Validated source/profile/native-output row from the capture manifest.
    qualification_output : pathlib.Path
        Durable directory for exclusive query receipts.

    Returns
    -------
    None
        Immutable source, profile and output bindings.
    """

    language: str
    root: Path
    source: Path
    profile: Path
    helper: Path
    build_receipt: Path
    capture: dict[str, object]
    qualification_output: Path


@dataclass(frozen=True)
class BackendQualificationRequest:
    """Inputs for one isolated backend persistence and evidence query.

    Parameters
    ----------
    case : NativeQualificationCase
        Durable source and native profile selected for the language.
    backend_name : str
        First-party structural backend name.
    analyzer_table : str
        Plugin configuration table for the selected language analyzer.
    symbol_names : tuple[str, ...]
        Exact indexed names whose evidence must be queried.
    storage_root : pathlib.Path
        Disposable per-backend database workspace.
    attempt_root : pathlib.Path
        Durable identity for helper invocations made by the analyzer plugin.

    Returns
    -------
    None
        Immutable inputs for one backend qualification.
    """

    case: NativeQualificationCase
    backend_name: str
    analyzer_table: str
    symbol_names: tuple[str, ...]
    storage_root: Path
    attempt_root: Path


def sha256_file(path: Path) -> str:
    """Return a bounded-memory digest of one file.

    Parameters
    ----------
    path : pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lowercase SHA-256 hexadecimal digest.

    Raises
    ------
    OSError
        If the file cannot be read.
    """
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_native_case(language: str) -> NativeQualificationCase:
    """Load and validate the durable capture for one language.

    Parameters
    ----------
    language : str
        ``c`` or ``cpp`` capture key.

    Returns
    -------
    NativeQualificationCase
        Hash-verified source/profile/helper identities for testing.

    Raises
    ------
    pytest.skip.Exception
        If the separate native qualification artifacts are unavailable.
    ValueError
        If any manifest, profile, source, or helper binding is stale.
    RuntimeError
        If the active working directory is not the repository root.
    OSError
        If an input artifact cannot be read.
    KeyError
        If the manifest omits a required field.
    json.JSONDecodeError
        If the capture manifest is malformed.
    """
    manifest_value = os.environ.get("CODIRA_CLANG_MACRO_CAPTURE_MANIFEST")
    output_value = os.environ.get("CODIRA_CLANG_MACRO_QUALIFICATION_OUTPUT")
    if not manifest_value or not output_value:
        pytest.skip("requires explicit durable native capture and qualification output")
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError
    manifest_path = Path(manifest_value).resolve()
    output = Path(output_value).resolve()
    if not manifest_path.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        raise ValueError
    receipt_prefix = "c" if language == "c" else "cpp"
    receipt_paths = [
        output / f"{receipt_prefix}-{backend}-qualification-r1.json"
        for backend in ("sqlite", "duckdb")
    ]
    if any(path.exists() for path in receipt_paths):
        raise ValueError
    manifest = cast(
        "dict[str, object]", json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    cases = cast("list[dict[str, object]]", manifest["cases"])
    matches = [row for row in cases if row.get("key") == language]
    if len(matches) != 1:
        raise ValueError
    capture = matches[0]
    source = Path(cast("str", capture["source_path"])).resolve()
    profile = Path(cast("str", capture["profile_path"])).resolve()
    helper_record = cast("dict[str, object]", manifest["helper"])
    build_record = cast("dict[str, object]", manifest["build_receipt"])
    helper = Path(cast("str", helper_record["path"])).resolve()
    build_receipt = Path(cast("str", build_record["path"])).resolve()
    fixture_name = (
        "c_file_scope_macro.c" if language == "c" else "cpp_namespace_static_macro.cpp"
    )
    fixture = FIXTURE_ROOT / fixture_name
    if capture["tracked_fixture_sha256"] != sha256_file(fixture):
        raise ValueError
    if not source.is_file() or sha256_file(source) != capture["source_sha256"]:
        raise ValueError
    if capture["source_sha256"] != capture["tracked_fixture_sha256"]:
        raise ValueError
    if sha256_file(profile) != capture["profile_sha256"]:
        raise ValueError
    if sha256_file(helper) != EXPECTED_HELPER_SHA256:
        raise ValueError
    if sha256_file(build_receipt) != EXPECTED_BUILD_RECEIPT_SHA256:
        raise ValueError
    raw_stdout = Path(cast("str", capture["stdout_path"]))
    raw_stderr = Path(cast("str", capture["stderr_path"]))
    if (
        sha256_file(raw_stdout) != capture["stdout_sha256"]
        or sha256_file(raw_stderr) != capture["stderr_sha256"]
    ):
        raise ValueError
    if capture["profile_status"] != "complete":
        raise ValueError
    return NativeQualificationCase(
        language,
        source.parent.parent,
        source,
        profile,
        helper,
        build_receipt,
        capture,
        output,
    )


def plugin_configuration(
    case: NativeQualificationCase, attempt_root: Path
) -> dict[str, object]:
    """Build the explicit Clang plugin configuration for one captured case.

    Parameters
    ----------
    case : NativeQualificationCase
        Validated native profile and helper binding.
    attempt_root : pathlib.Path
        Unique durable root for the new analyzer helper attempts.

    Returns
    -------
    dict[str, object]
        Minimal explicit Clang configuration with no inferred compiler flags.
    """
    return {
        "frontend": "clang",
        "clang_captured_profiles": str(case.profile),
        "clang_helper_path": str(case.helper),
        "clang_build_receipt_path": str(case.build_receipt),
        "clang_attempt_root": str(attempt_root),
    }


def run_index_and_query(
    request: BackendQualificationRequest,
) -> dict[str, object]:
    """Run a real index, persist to one backend, and query symbol evidence.

    Parameters
    ----------
    request : BackendQualificationRequest
        Source, backend, plugin, and workspace identities for this run.

    Returns
    -------
    dict[str, object]
        Index summary, actual database digest, symbol match, and verified query result.

    Raises
    ------
    AssertionError
        If indexing, symbol lookup, or backend metadata fails qualification.
    BackendError
        If the selected backend rejects a repository-scoped mutation.
    OSError
        If configuration, indexing, or database storage fails.
    RuntimeError
        If a backend runtime operation fails.
    ValueError
        If indexed provenance is invalid or no longer matches its source inputs.
    """
    case = request.case
    backend_name = request.backend_name
    storage_root = request.storage_root
    plugin = plugin_configuration(case, request.attempt_root)
    config_dir = storage_root / ".codira"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = (
        "config_version = 2\n"
        f'[backend]\nname = "{backend_name}"\n'
        '[embeddings]\nenabled = false\nsimilarity_index = "exact"\n'
        f"[plugins.{request.analyzer_table}]\n"
        + "\n".join(f"{key} = {json.dumps(value)}" for key, value in plugin.items())
        + "\n"
    )
    (config_dir / "config.toml").write_text(config, encoding="utf-8")
    prior_git_ceiling = os.environ.get("GIT_CEILING_DIRECTORIES")
    os.environ["GIT_CEILING_DIRECTORIES"] = str(case.root.parent)
    try:
        with (
            override_repo_config_path(config_dir / "config.toml"),
            override_storage_root(case.root, storage_root),
        ):
            report = index_repo(case.root, full=True)
            if report.failed != 0 or report.indexed != 1:
                raise AssertionError
            adapter = MCPAdapter(case.root)
            queried: dict[str, dict[str, object]] = {}
            for symbol_name in request.symbol_names:
                inventory = adapter.symbol(symbol_name)
                result = cast("dict[str, object]", inventory["result"])
                symbols = cast("list[dict[str, object]]", result["symbols"])
                if len(symbols) != 1:
                    raise AssertionError
                identity = cast("str", symbols[0]["identity"])
                evidence = cast(
                    "dict[str, object]", adapter.symbol_evidence(identity)["result"]
                )
                queried[symbol_name] = {"symbol": symbols[0], "evidence": evidence}
            status = cast(
                "dict[str, object]", adapter.index_status(detail=True)["result"]
            )
    finally:
        if prior_git_ceiling is None:
            os.environ.pop("GIT_CEILING_DIRECTORIES", None)
        else:
            os.environ["GIT_CEILING_DIRECTORIES"] = prior_git_ceiling
    db_path = (
        storage_root
        / ".codira"
        / ("index.db" if backend_name == "sqlite" else "index.duckdb")
    )
    if not db_path.is_file():
        raise AssertionError
    metadata = cast("dict[str, object]", status["metadata"])
    if metadata.get("backend_name") != backend_name:
        raise AssertionError
    return {
        "backend_name": backend_name,
        "indexed_file_count": report.indexed,
        "failed_file_count": report.failed,
        "database_sha256": sha256_file(db_path),
        "persisted_metadata": metadata,
        "queried_symbols": queried,
        "index_status": status,
    }


def write_qualification_receipt(path: Path, payload: dict[str, object]) -> None:
    """Write one fully validated durable qualification receipt exactly once.

    Parameters
    ----------
    path : pathlib.Path
        New receipt path under the durable qualification output identity.
    payload : dict[str, object]
        Fully assembled source/profile/index/query evidence.

    Returns
    -------
    None
        Canonical JSON bytes are validated before exclusive creation and fsynced.

    Raises
    ------
    FileExistsError
        If the receipt path already exists.
    OSError
        If the receipt cannot be written or synchronized.
    TypeError
        If the payload contains a value that JSON cannot serialize.
    ValueError
        If the payload contains a non-finite number or fails round-trip validation.
    """
    raw = (
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if json.loads(raw) != payload:
        raise ValueError
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
