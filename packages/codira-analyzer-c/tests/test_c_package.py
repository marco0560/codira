"""Package-local tests for the first-party C analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_c import CAnalyzer, build_analyzer


def test_c_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "1.42.0"
    assert "codira>=1.5.0,<2.0.0" in project["project"]["dependencies"]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "c": "codira_analyzer_c:build_analyzer"
    }


def test_c_package_builds_expected_analyzer() -> None:
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

    assert isinstance(analyzer, CAnalyzer)
    assert analyzer.name == "c"


def test_c_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply C analyzer documentation, import, and macro toggles.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured options prune optional C artifacts.
    """

    source = tmp_path / "src" / "sample.c"
    source.parent.mkdir()
    source.write_text(
        "/// Module docs.\n"
        "#include <stdio.h>\n"
        "#define VALUE 1\n"
        "/// Function docs.\n"
        "int run(void) { return VALUE; }\n",
        encoding="utf-8",
    )

    analyzer = CAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "include_paths": ["src"],
            "use_leading_comments": False,
            "emit_doxygen_documentation": False,
            "include_system_includes": False,
            "emit_macros": False,
        }
    )
    analysis = analyzer.analyze_file(source, tmp_path)

    assert "emit_macros" in properties
    assert analyzer.allows_path(source, tmp_path) is True
    assert analysis.module.docstring is None
    assert analysis.imports == ()
    assert analysis.documentation == ()
    assert all(declaration.kind != "macro" for declaration in analysis.declarations)


def test_c_analyzer_emits_doxygen_documentation_only(tmp_path: Path) -> None:
    """
    Keep C documentation artifacts scoped to explicit Doxygen comments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts Doxygen comments produce documentation artifacts while
        ordinary comments do not.
    """
    source = tmp_path / "sample.c"
    source.write_text(
        "\n".join(
            (
                "/// Adds one to the value.",
                "int documented(int value) { return value + 1; }",
                "",
                "// Ordinary implementation note.",
                "int undocumented(int value) { return value; }",
            )
        ),
        encoding="utf-8",
    )

    analysis = CAnalyzer().analyze_file(source, tmp_path)

    assert [
        (doc.title, doc.source_format, doc.owner_kind) for doc in analysis.documentation
    ] == [("documented", "doxygen", "function")]
    assert analysis.documentation[0].text == "Adds one to the value."
    assert analysis.documentation[0].attachment_confidence == "explicit"
