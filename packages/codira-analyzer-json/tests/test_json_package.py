"""Package-local tests for the first-party JSON analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_json import JsonAnalyzer, build_analyzer


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

    assert project["project"]["version"] == "1.40.0"
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
        "json_schema_definition"
    ]
