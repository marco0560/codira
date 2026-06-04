"""Package-local tests for the first-party plain-text analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_text import TextAnalyzer, build_analyzer


def test_text_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "1.43.0"
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "text": "codira_analyzer_text:build_analyzer"
    }


def test_text_package_builds_expected_analyzer() -> None:
    """
    Keep the package-local factory aligned to the published analyzer name.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the factory returns the expected analyzer type and
        name.
    """
    analyzer = build_analyzer()

    assert isinstance(analyzer, TextAnalyzer)
    assert analyzer.name == "text"


def test_text_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply text analyzer path-policy and include/exclude options.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured policy controls accepted text paths.
    """

    readme = tmp_path / "README.txt"
    readme.write_text("Repository overview.\n", encoding="utf-8")
    generated = tmp_path / "docs" / "generated" / "api.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("Generated API.\n", encoding="utf-8")

    analyzer = TextAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "include_paths": ["docs"],
            "include_root_files": False,
            "include_docs_directories": True,
            "exclude_generated": False,
            "exclude_fixtures_logs": True,
        }
    )

    assert "exclude_generated" in properties
    assert analyzer.allows_path(readme, tmp_path) is False
    assert analyzer.allows_path(generated, tmp_path) is True
    assert len(analyzer.analyze_file(generated, tmp_path).documentation) == 1


def test_text_analyzer_accepts_documentation_scoped_txt(tmp_path: Path) -> None:
    """
    Emit plain-text documentation artifacts only for accepted paths.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts docs-scoped text is indexed as documentation.
    """
    doc_path = tmp_path / "docs" / "process" / "release.txt"
    doc_path.parent.mkdir(parents=True)
    doc_path.write_text("Release process notes.\n", encoding="utf-8")

    result = TextAnalyzer().analyze_file(doc_path, tmp_path)

    assert result.index_symbols is False
    assert len(result.documentation) == 1
    artifact = result.documentation[0]
    assert artifact.kind == "file"
    assert artifact.source_format == "plain_text_document"
    assert artifact.stable_id == "doc:file:docs/process/release.txt:plain-text:1"
    assert artifact.text == "Release process notes."


def test_text_analyzer_excludes_fixtures_logs_and_generated_outputs(
    tmp_path: Path,
) -> None:
    """
    Keep arbitrary and generated text out of documentation retrieval.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts non-documentation text files produce no documentation
        artifacts.
    """
    paths = [
        tmp_path / "tests" / "fixtures" / "sample.txt",
        tmp_path / "docs" / "generated" / "api.txt",
        tmp_path / "docs" / "release.log.txt",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Not indexed.\n", encoding="utf-8")

    analyzer = TextAnalyzer()

    assert [analyzer.analyze_file(path, tmp_path).documentation for path in paths] == [
        (),
        (),
        (),
    ]


def test_text_analyzer_accepts_named_root_docs(tmp_path: Path) -> None:
    """
    Accept conventional root documentation filenames.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts README, CHANGELOG, and LICENSE text files are
        documentation by filename policy.
    """
    readme = tmp_path / "README.txt"
    readme.write_text("Repository overview.\n", encoding="utf-8")

    result = TextAnalyzer().analyze_file(readme, tmp_path)

    assert len(result.documentation) == 1
    assert result.documentation[0].source_format == "plain_text_document"
