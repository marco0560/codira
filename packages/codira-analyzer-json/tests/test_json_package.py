"""Package-local tests for the first-party JSON analyzer distribution."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from codira_analyzer_json import (
    JsonAnalyzer,
    _classify_json_document_with_facets,
    _load_json_mapping,
    build_analyzer,
)


def test_json_package_declares_expected_entry_point() -> None:
    """
    Keep package metadata aligned to the analyzer entry-point contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the package advertises the expected analyzer factory.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert project["project"]["version"] == "1.56.0"
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "json": "codira_analyzer_json:build_analyzer"
    }


def test_json_package_builds_expected_analyzer() -> None:
    """
    Keep the package-local factory aligned to the published analyzer name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected analyzer type and name.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, JsonAnalyzer)
    assert analyzer.name == "json"


def test_json_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply JSON analyzer family and artifact toggles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured JSON options prune optional artifacts.
    """

    schema_path = tmp_path / "schema" / "example.schema.json"
    schema_path.parent.mkdir()
    schema_path.write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema",'
        '"definitions":{"Thing":{"type":"object"}},'
        '"properties":{"name":{"type":"string"}}}',
        encoding="utf-8",
    )
    package_path = tmp_path / "package.json"
    package_path.write_text(
        '{"name":"demo","scripts":{"test":"pytest"},"dependencies":{"codira":"1.0.0"}}',
        encoding="utf-8",
    )

    analyzer = JsonAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "enabled_families": ["schema"],
            "emit_schema_properties": False,
            "emit_scripts": False,
            "emit_dependencies": False,
        }
    )

    result = analyzer.analyze_file(schema_path, tmp_path)

    assert "enabled_families" in properties
    assert analyzer.supports_path(schema_path) is True
    assert analyzer.supports_path(package_path) is False
    assert [declaration.kind for declaration in result.declarations] == [
        "json_schema_definition",
        "json_manifest_facet",
        "json_manifest_facet",
    ]


def test_json_analyzer_classifies_known_documents_with_composable_facets(
    tmp_path: Path,
) -> None:
    """
    Preserve npm recognition while adding its independent semantic facets.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts known documents retain deterministic facet evidence.
    """
    source = tmp_path / "package.json"
    source.write_text(
        '{"name":"demo","version":"1.0.0","scripts":{"test":"pytest"}}',
        encoding="utf-8",
    )

    classification = _classify_json_document_with_facets(
        source,
        _load_json_mapping(source),
    )

    assert classification is not None
    assert classification.primary_family == "npm_package_manifest"
    assert classification.facets == (
        "json",
        "manifest",
        "package_metadata",
        "build_configuration",
    )
    assert classification.known_ecosystem == "npm"
    assert classification.evidence == ("recognizer:npm_package_manifest",)


def test_json_analyzer_claims_only_evidenced_generic_manifests(tmp_path: Path) -> None:
    """
    Require structural and corroborating evidence for generic manifest support.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts generic-manifest evidence is deterministic and bounded.
    """
    source = tmp_path / "config" / "service-manifest.json"
    source.parent.mkdir()
    source.write_text(
        """{
        "services": {"api": {"path": "src/api"}},
        "deployments": [{"name": "production"}],
        "homepage": "https://example.invalid/service"
        }""",
        encoding="utf-8",
    )

    classification = _classify_json_document_with_facets(
        source,
        _load_json_mapping(source),
    )

    assert classification is not None
    assert classification.primary_family == "generic_manifest"
    assert classification.facets == ("json", "manifest")
    assert classification.known_ecosystem is None
    assert classification.evidence == (
        "structural:multiple_compound_top_level_values",
        "corroboration:repository_context",
        "corroboration:filename",
        "corroboration:meaningful_url_or_path",
    )
    assert classification.score == 5
    assert JsonAnalyzer().supports_path(source) is True


def test_json_analyzer_rejects_filename_only_generic_manifest(tmp_path: Path) -> None:
    """
    Keep a manifest-like filename from becoming sufficient classification evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts filename evidence never claims an arbitrary JSON blob.
    """
    source = tmp_path / "manifest.json"
    source.write_text('{"task":"build"}', encoding="utf-8")

    assert (
        _classify_json_document_with_facets(
            source,
            _load_json_mapping(source),
        )
        is None
    )
    assert JsonAnalyzer().supports_path(source) is False


def test_json_analyzer_extracts_bounded_generic_manifest_facts(tmp_path: Path) -> None:
    """
    Emit generic structure without assigning an unknown manifest an ecosystem.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts bounded keys, paths, arrays, references, and locators.
    """
    source = tmp_path / "config" / "service-manifest.json"
    source.parent.mkdir()
    source.write_text(
        """{
        "services": {"api": {"path": "src/api", "$ref": "schemas/api.json"}},
        "deployments": [{"name": "production"}],
        "homepage": "https://example.invalid/service"
        }""",
        encoding="utf-8",
    )

    result = JsonAnalyzer().analyze_file(source, tmp_path)
    declaration_rows = {
        (declaration.kind, declaration.name, declaration.signature)
        for declaration in result.declarations
    }

    assert (
        "json_manifest_top_level_key",
        "services",
        "manifest top-level key services",
    ) in declaration_rows
    assert (
        "json_manifest_object_path",
        "services.api",
        "manifest object path=services.api",
    ) in declaration_rows
    assert (
        "json_manifest_array",
        "deployments",
        "manifest array path=deployments entries=1",
    ) in declaration_rows
    assert (
        "json_manifest_reference",
        "services.api.$ref",
        "manifest reference path=services.api.$ref target=schemas/api.json",
    ) in declaration_rows
    assert (
        "json_manifest_url",
        "homepage",
        "manifest URL path=homepage value=https://example.invalid/service",
    ) in declaration_rows
    assert (
        "json_manifest_path",
        "services.api.path",
        "manifest path path=services.api.path value=src/api",
    ) in declaration_rows
    assert all(
        declaration.kind != "json_manifest_name" for declaration in result.declarations
    )


def test_json_analyzer_can_disable_generic_manifest_fact_emission(
    tmp_path: Path,
) -> None:
    """
    Keep generic-manifest admission independent from optional fact emission.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
    The test asserts disabled structural facts preserve persisted facets.
    """
    source = tmp_path / "config" / "service-manifest.json"
    source.parent.mkdir()
    source.write_text(
        '{"services":{"api":{}},"deployments":[],"homepage":"https://example.invalid"}',
        encoding="utf-8",
    )
    analyzer = JsonAnalyzer()
    analyzer.configure({"emit_generic_facts": False})

    assert analyzer.supports_path(source) is True
    assert [
        declaration.name
        for declaration in analyzer.analyze_file(source, tmp_path).declarations
    ] == ["json", "manifest"]


def test_json_analyzer_persists_facets_and_known_ecosystem(tmp_path: Path) -> None:
    """Expose classification facts through ordinary declaration artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts facets and the known ecosystem have stable kinds.
    """
    source = tmp_path / "package.json"
    source.write_text(
        '{"name":"demo","version":"1.0.0","scripts":{"test":"pytest"}}',
        encoding="utf-8",
    )

    declarations = JsonAnalyzer().analyze_file(source, tmp_path).declarations

    assert ("json_manifest_facet", "json") in {
        (declaration.kind, declaration.name) for declaration in declarations
    }
    assert ("json_manifest_ecosystem", "npm") in {
        (declaration.kind, declaration.name) for declaration in declarations
    }


def test_json_analyzer_reports_generic_manifest_fact_truncation(tmp_path: Path) -> None:
    """
    Make bounded generic fact extraction observable to downstream consumers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts depth limits emit one deterministic truncation fact.
    """
    source = tmp_path / "config" / "service-manifest.json"
    source.parent.mkdir()
    source.write_text(
        json.dumps(
            {
                "services": {"api": {"nested": {"again": {"deep": {}}}}},
                "deployments": [],
                "homepage": "https://example.invalid",
            }
        ),
        encoding="utf-8",
    )

    truncation = [
        declaration
        for declaration in JsonAnalyzer().analyze_file(source, tmp_path).declarations
        if declaration.kind == "json_manifest_truncation"
    ]

    assert len(truncation) == 1
    assert "depth=4" in truncation[0].signature
