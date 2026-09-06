"""Tests for ADR-004 Phase 3 contract and normalization models.

Responsibilities
----------------
- Verify analyzer and backend contracts using fake implementations that hook into the existing registry.
- Ensure normalization from parser output produces the expected AnalysisResult artifacts and deterministic module data.
- Validate registry discovery, analyzer selection, and backend initialization invariants.

Design principles
-----------------
Tests rely on stub analyzers/backends and explicit fixtures so contract violations surface as deterministic failures.

Architectural role
------------------
This module belongs to the **contract verification layer** and enforces the ADR-004 Phase 3 language analyzer and backend APIs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import codira_analyzer_json as json_analyzer_module
from codira_analyzer_json import JsonAnalyzer

import codira.registry as registry_module
from codira.indexer import _select_language_analyzer
from codira.registry import missing_language_analyzer_hint

if TYPE_CHECKING:
    from pytest import MonkeyPatch

    from codira.contracts import LanguageAnalyzer


def test_json_analyzer_extracts_module_metadata_from_json_schema(
    tmp_path: Path,
) -> None:
    """
    Analyze one JSON Schema document into a module-only artifact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts schema documents become stable module artifacts.
    """
    source = tmp_path / "src" / "codira" / "schema" / "context.schema.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "codira context output",
                "description": "Validate ctx JSON output.",
                "type": "object",
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)

    assert result.module.name == "src.codira.schema.context_schema"
    assert (
        result.module.stable_id == "json:module:src/codira/schema/context.schema.json"
    )
    assert (
        result.module.docstring
        == "JSON Schema: codira context output. Validate ctx JSON output."
    )
    assert result.classes == ()
    assert result.functions == ()
    assert [
        (declaration.kind, declaration.name) for declaration in result.declarations
    ] == [
        ("json_manifest_facet", "json"),
        ("json_manifest_facet", "schema"),
    ]
    assert result.imports == ()


def test_json_analyzer_rejects_unclassified_json_documents(tmp_path: Path) -> None:
    """
    Leave generic JSON blobs unclaimed by the JSON analyzer.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts unsupported JSON files remain outside analyzer scope.
    """
    source = tmp_path / "scripts" / "build.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"task": "build"}\n', encoding="utf-8")

    assert JsonAnalyzer().supports_path(source) is False


def test_json_analyzer_rejects_generic_json_without_full_parse(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Skip full JSON parsing for obvious unsupported generic JSON blobs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to guard the full-parse helper.

    Returns
    -------
    None
        The test asserts shallow sniffing rejects the file before a full JSON
        parse is attempted.
    """
    source = tmp_path / "scripts" / "build.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"task": "build"}\n', encoding="utf-8")

    def _unexpected_parse(path: Path) -> dict[str, object]:
        msg = f"_load_json_mapping should not be called for {path}"
        raise AssertionError(msg)

    monkeypatch.setattr(json_analyzer_module, "_load_json_mapping", _unexpected_parse)

    assert JsonAnalyzer().supports_path(source) is False


def test_json_analyzer_rejects_schemaish_paths_without_schema_markers(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Skip full parsing for schema-like paths that lack schema markers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to guard the full-parse helper.

    Returns
    -------
    None
        The test asserts schema-name heuristics still require shallow schema
        markers before JSON parsing begins.
    """
    source = tmp_path / "src" / "codira" / "schema" / "build.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"task": "build"}\n', encoding="utf-8")

    def _unexpected_parse(path: Path) -> dict[str, object]:
        msg = f"_load_json_mapping should not be called for {path}"
        raise AssertionError(msg)

    monkeypatch.setattr(json_analyzer_module, "_load_json_mapping", _unexpected_parse)

    assert JsonAnalyzer().supports_path(source) is False


def test_json_analyzer_accepts_supported_schema_on_ambiguous_path(
    tmp_path: Path,
) -> None:
    """
    Keep payload-based fallback support for supported JSON on neutral paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts shallow marker sniffing still permits a full parse
        for supported schema payloads outside schema-named paths.
    """
    source = tmp_path / "configs" / "context.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {"status": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )

    assert JsonAnalyzer().supports_path(source) is True


def test_json_analyzer_extracts_schema_properties_and_definitions(
    tmp_path: Path,
) -> None:
    """
    Extract deterministic definition and property symbols from JSON Schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts the JSON analyzer emits schema-specific declarations.
    """
    source = tmp_path / "src" / "codira" / "schema" / "example.schema.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "$defs": {
                    "Channel": {
                        "type": "string",
                        "description": "One retrieval channel.",
                    }
                },
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Rendered query status.",
                    },
                    "explain": {
                        "type": "object",
                        "properties": {
                            "planner": {"type": "object"},
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature, decl.docstring)
        for decl in result.declarations
    ]

    assert (
        "json_schema_definition",
        "Channel",
        "definition Channel type=string",
        "One retrieval channel.",
    ) in declaration_rows
    assert (
        "json_schema_property",
        "status",
        "property path=status type=string",
        "Rendered query status.",
    ) in declaration_rows
    assert (
        "json_schema_property",
        "explain.planner",
        "property path=explain.planner type=object",
        None,
    ) in declaration_rows


def test_json_analyzer_extracts_package_manifest_symbols(tmp_path: Path) -> None:
    """
    Extract stable manifest symbols from one ``package.json`` file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts package, script, and dependency symbols are emitted.
    """
    source = tmp_path / "package.json"
    source.write_text(
        json.dumps(
            {
                "name": "codira-release",
                "version": "1.2.3",
                "scripts": {"release": "semantic-release"},
                "devDependencies": {"semantic-release": "^23.0.0"},
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature) for decl in result.declarations
    ]

    assert (
        "json_manifest_name",
        "codira-release",
        "package name=codira-release version=1.2.3",
    ) in declaration_rows
    assert (
        "json_manifest_script",
        "release",
        "package script release: semantic-release",
    ) in declaration_rows
    assert (
        "json_manifest_dependency",
        "semantic-release",
        "package dependency section=devDependencies name=semantic-release version=^23.0.0",
    ) in declaration_rows


def test_json_analyzer_extracts_semantic_release_symbols(tmp_path: Path) -> None:
    """
    Extract stable branch and plugin symbols from semantic-release config.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root for the fixture.

    Returns
    -------
    None
        The test asserts semantic-release symbols are emitted deterministically.
    """
    source = tmp_path / ".releaserc.json"
    source.write_text(
        json.dumps(
            {
                "branches": ["main", {"name": "next"}],
                "plugins": [
                    "@semantic-release/commit-analyzer",
                    ["@semantic-release/git", {"assets": ["CHANGELOG.md"]}],
                ],
            }
        ),
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = [
        (decl.kind, decl.name, decl.signature) for decl in result.declarations
    ]

    assert (
        "json_release_branch",
        "main",
        "semantic-release branch main",
    ) in declaration_rows
    assert (
        "json_release_branch",
        "next",
        "semantic-release branch next",
    ) in declaration_rows
    assert (
        "json_release_plugin",
        "@semantic-release/commit-analyzer",
        "semantic-release plugin @semantic-release/commit-analyzer",
    ) in declaration_rows
    assert (
        "json_release_plugin",
        "@semantic-release/git",
        "semantic-release plugin @semantic-release/git",
    ) in declaration_rows


def test_select_language_analyzer_reports_optional_extra_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a C-family file has no available analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the C package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("native/sample.c"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing optional C analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: native/sample.c" in message
    assert "codira-analyzer-c" in message
    assert missing_language_analyzer_hint(Path("native/sample.c")) is not None


def test_select_language_analyzer_reports_cpp_package_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a C++ file has no available analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the C++ package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("native/sample.cpp"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing optional C++ analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: native/sample.cpp" in message
    assert "codira-analyzer-cpp" in message
    assert missing_language_analyzer_hint(Path("native/sample.cpp")) is not None


def test_missing_language_analyzer_hints_cover_go_javascript_and_typescript(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report package install hints for unavailable Go and web-language analyzers.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts every supported suffix has its first-party package hint.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    expected_packages_by_path = {
        Path("native/sample.go"): "codira-analyzer-go",
        Path("web/sample.js"): "codira-analyzer-javascript",
        Path("web/sample.ts"): "codira-analyzer-typescript",
    }

    for path, package_name in expected_packages_by_path.items():
        hint = missing_language_analyzer_hint(path)
        assert hint is not None
        assert package_name in hint


def test_select_language_analyzer_reports_python_package_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a Python file has no available analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the Python package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("pkg/sample.py"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing Python analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: pkg/sample.py" in message
    assert "codira-analyzer-python" in message
    assert missing_language_analyzer_hint(Path("pkg/sample.py")) is not None


def test_select_language_analyzer_reports_json_package_hint(
    monkeypatch: MonkeyPatch,
) -> None:
    """
    Report the package install hint when a supported JSON file has no analyzer.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Pytest fixture used to patch entry-point discovery.

    Returns
    -------
    None
        The test asserts the failure message includes the JSON package hint.

    Notes
    -----
    The test captures the ``ValueError`` internally, so it does not expose a
    ``Raises`` contract to callers.
    """
    monkeypatch.setattr(
        registry_module,
        "_entry_points_for_group",
        lambda group: [],
    )

    analyzers: list[LanguageAnalyzer] = []

    try:
        _select_language_analyzer(Path("package.json"), analyzers)
    except ValueError as exc:
        message = str(exc)
    else:
        msg = "expected ValueError for missing JSON analyzer"
        raise AssertionError(msg)

    assert "No language analyzer registered for path: package.json" in message
    assert "codira-analyzer-json" in message
    assert missing_language_analyzer_hint(Path("package.json")) is not None
