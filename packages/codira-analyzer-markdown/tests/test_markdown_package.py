"""Package-local tests for the first-party Markdown analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_markdown import MarkdownAnalyzer, build_analyzer


def test_markdown_package_declares_expected_entry_point() -> None:
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
        "markdown": "codira_analyzer_markdown:build_analyzer"
    }


def test_markdown_package_builds_expected_analyzer() -> None:
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

    assert isinstance(analyzer, MarkdownAnalyzer)
    assert analyzer.name == "markdown"


def test_markdown_analyzer_emits_heading_section_documentation(
    tmp_path: Path,
) -> None:
    """
    Emit deterministic section artifacts from Markdown headings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts front matter is ignored, fenced headings stay inside
        their owner section, and repeated headings get deterministic ordinals.
    """
    doc_path = tmp_path / "docs" / "guide.md"
    doc_path.parent.mkdir()
    doc_path.write_text(
        "---\n"
        "title: Ignored\n"
        "---\n"
        "# Setup\n"
        "\n"
        "Install the package.\n"
        "\n"
        "```python\n"
        "# Not a heading\n"
        "```\n"
        "\n"
        "## Details\n"
        "More text.\n"
        "\n"
        "# Setup\n"
        "Second setup.\n",
        encoding="utf-8",
    )

    result = MarkdownAnalyzer().analyze_file(doc_path, tmp_path)

    assert result.module.name == "docs.docs.guide"
    assert result.classes == ()
    assert result.functions == ()
    assert result.declarations == ()
    assert result.imports == ()
    assert result.index_symbols is False
    assert [artifact.title for artifact in result.documentation] == [
        "Setup",
        "Details",
        "Setup",
    ]
    assert [artifact.stable_id for artifact in result.documentation] == [
        "doc:section:docs/guide.md:setup:1",
        "doc:section:docs/guide.md:setup/details:1",
        "doc:section:docs/guide.md:setup:2",
    ]
    assert result.documentation[0].lineno == 4
    assert "# Not a heading" in result.documentation[0].text


def test_markdown_analyzer_emits_file_artifact_without_headings(
    tmp_path: Path,
) -> None:
    """
    Preserve heading-less Markdown as one file-level documentation artifact.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts non-empty heading-less files are still retrievable.
    """
    readme_path = tmp_path / "README.md"
    readme_path.write_text("Repository overview.\n", encoding="utf-8")

    result = MarkdownAnalyzer().analyze_file(readme_path, tmp_path)

    assert len(result.documentation) == 1
    artifact = result.documentation[0]
    assert artifact.kind == "file"
    assert artifact.source_format == "markdown_section"
    assert artifact.stable_id == "doc:file:README.md:file:1"
    assert artifact.text == "Repository overview."
