"""Package-local tests for the first-party Bash analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_bash import BashAnalyzer, build_analyzer


def test_bash_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "1.41.0"
    assert "codira>=1.5.0,<2.0.0" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "bash": "codira_analyzer_bash:build_analyzer"
    }


def test_bash_package_builds_expected_analyzer() -> None:
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

    assert isinstance(analyzer, BashAnalyzer)
    assert analyzer.name == "bash"


def test_bash_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply Bash analyzer path filters and function emission toggle.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured options affect shell analysis.
    """

    source = tmp_path / "scripts" / "tool.sh"
    source.parent.mkdir()
    source.write_text("run() { echo ok; }\n", encoding="utf-8")

    analyzer = BashAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure({"include_paths": ["scripts"], "emit_functions": False})
    result = analyzer.analyze_file(source, tmp_path)

    assert "emit_functions" in properties
    assert analyzer.allows_path(source, tmp_path) is True
    assert result.functions == ()
