"""Package-local tests for the first-party Python analyzer distribution."""

from __future__ import annotations

import ast
from dataclasses import asdict
import json
import sys
import tomllib
from pathlib import Path
from typing import cast

import pytest

from codira_analyzer_python import PythonAnalyzer, build_analyzer
from codira.models import AnalysisCoverageState, AnalysisResult
from codira.target_python import (
    PYTHON_TARGET_GRAMMAR,
    PYTHON_TARGET_GRAMMAR_MAXIMUM_MINOR,
    SUPPORTED_TARGET_PYTHON_MINORS,
    TESTED_TARGET_PYTHON_MINORS,
)

_COMPATIBILITY_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "compatibility"
_COMPATIBILITY_FIXTURES = {
    "3.8": "python38.py.txt",
    "3.9": "python39.py.txt",
    "3.10": "python310.py.txt",
    "3.11": "python311.py.txt",
    "3.12": "python312.py.txt",
    "3.13": "python313.py.txt",
    "3.14": "python314.py.txt",
}


def _golden_analysis_payload(
    result: AnalysisResult,
    root: Path,
) -> dict[str, object]:
    """
    Convert one analyzer result into a portable golden-fixture payload.

    Parameters
    ----------
    result : codira.models.AnalysisResult
        Analysis result emitted for the characterization source.
    root : pathlib.Path
        Fixture directory used to make source paths portable.

    Returns
    -------
    dict[str, object]
        JSON-compatible result with fixture-relative source paths.
    """
    payload = cast(
        "dict[str, object]",
        json.loads(json.dumps(asdict(result), default=str)),
    )
    payload.pop("status")
    payload["source_path"] = str(
        Path(cast("str", payload["source_path"])).relative_to(root)
    )
    documentation = payload["documentation"]
    assert isinstance(documentation, list)
    for artifact in documentation:
        assert isinstance(artifact, dict)
        artifact["source_path"] = str(
            Path(cast("str", artifact["source_path"])).relative_to(root)
        )
    return payload


def test_python_analyzer_matches_runtime_decoupling_golden_fixture() -> None:
    """
    Preserve normalized Python artifacts across the parser migration.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the frozen artifact payload matches the fixture.
    """
    fixture_root = Path(__file__).parent / "fixtures"
    source = fixture_root / "runtime_decoupling_baseline.py"
    expected = json.loads(
        (fixture_root / "runtime_decoupling_baseline.json").read_text(encoding="utf-8")
    )

    result = PythonAnalyzer().analyze_file(source, fixture_root)

    assert _golden_analysis_payload(result, fixture_root) == expected


def test_python_analyzer_production_path_avoids_host_ast_parser() -> None:
    """Keep persisted Python analysis on the package-owned Tree-sitter path.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts the analyzer package has no host-AST parser import.
    """
    package_root = (
        Path(__file__).resolve().parents[1] / "src" / "codira_analyzer_python"
    )
    production_source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(package_root.glob("*.py"))
    )

    assert "import ast" not in production_source
    assert "codira.parser_ast" not in production_source


def test_python_analyzer_keeps_shebang_prefixed_module_documentation(
    tmp_path: Path,
) -> None:
    """Recognize a module docstring after the script shebang comment.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the syntax adapter preserves module documentation.
    """
    source = tmp_path / "scripts" / "sample.py"
    source.parent.mkdir()
    source.write_text(
        '#!/usr/bin/env python3\n"""Run the sample utility."""\n',
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(source, tmp_path)

    assert result.module.docstring == "Run the sample utility."
    assert result.documentation[0].lineno == 2


def test_python_analyzer_reports_target_version_feature_diagnostics(
    tmp_path: Path,
) -> None:
    """Report parseable syntax that exceeds a declared target version.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts target compatibility is independent of host parsing.
    """
    source = tmp_path / "sample.py"
    source.write_text("match value:\n    case _: pass\n", encoding="utf-8")
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": ">=3.9,<3.10"})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.PARTIAL
    assert result.status.diagnostics[0].category == "target_version"
    assert result.functions == ()


@pytest.mark.parametrize("minor", SUPPORTED_TARGET_PYTHON_MINORS)
def test_python_analyzer_accepts_every_advertised_target_fixture(
    minor: str,
    tmp_path: Path,
) -> None:
    """Parse each explicit target-minor fixture under its compatible contract.

    Parameters
    ----------
    minor : str
        Advertised Python target minor whose fixture is analyzed.
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts valid syntax retains complete analysis status.
    """
    fixture = _COMPATIBILITY_FIXTURE_ROOT / _COMPATIBILITY_FIXTURES[minor]
    source = tmp_path / "target.py"
    source.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": f"=={minor}.*"})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.grammar == PYTHON_TARGET_GRAMMAR
    assert result.status.coverage_state is AnalysisCoverageState.COMPLETE
    assert result.status.diagnostics == ()
    assert result.index_symbols is True


def test_target_matrix_cannot_advertise_an_unfixtureed_or_unbounded_minor() -> None:
    """Keep target release claims exactly aligned to the explicit fixtures.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test fails when an advertised or tested minor lacks a fixture, or
        when the declared grammar maximum differs from the tested maximum.
    """
    fixture_names = {
        path.name for path in _COMPATIBILITY_FIXTURE_ROOT.glob("python*.py.txt")
    }

    assert SUPPORTED_TARGET_PYTHON_MINORS == TESTED_TARGET_PYTHON_MINORS
    assert tuple(_COMPATIBILITY_FIXTURES) == TESTED_TARGET_PYTHON_MINORS
    assert set(_COMPATIBILITY_FIXTURES.values()) == fixture_names
    assert PYTHON_TARGET_GRAMMAR_MAXIMUM_MINOR == TESTED_TARGET_PYTHON_MINORS[-1]


def test_minimum_codira_host_parses_future_target_syntax_without_host_ast(
    tmp_path: Path,
) -> None:
    """Analyze the Python 3.14 fixture from the supported Python 3.13 host.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts Tree-sitter accepts future target syntax even when
        the host ``ast`` parser rejects it.
    """
    source_text = (_COMPATIBILITY_FIXTURE_ROOT / "python314.py.txt").read_text(
        encoding="utf-8"
    )
    source = tmp_path / "future_target.py"
    source.write_text(source_text, encoding="utf-8")

    result = PythonAnalyzer().analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.COMPLETE
    if sys.version_info[:2] == (3, 13):
        with pytest.raises(SyntaxError):
            ast.parse(source_text)


def test_python_analyzer_reports_future_fixture_for_conflicting_requirement(
    tmp_path: Path,
) -> None:
    """Classify valid newer grammar syntax as partial for an older target.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts parseability and target compatibility remain distinct.
    """
    source = tmp_path / "future_target.py"
    source.write_text(
        (_COMPATIBILITY_FIXTURE_ROOT / "python314.py.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": "==3.13.*"})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.PARTIAL
    assert result.status.diagnostics[0].category == "target_version"
    assert result.index_symbols is True


def test_python_analyzer_ignores_target_syntax_text_in_strings_and_comments(
    tmp_path: Path,
) -> None:
    """Ignore target-syntax-looking text outside parsed syntax constructs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
    The test asserts ordinary strings, comments, and docstrings stay
    compatible with the declared Python 3.13 target.
    """
    source = tmp_path / "ordinary_text.py"
    source.write_text(
        'option = "-t"\n'
        'text = "except * is mentioned here"\n'
        'description = """\\nmatch something:\ntype T = int\n"""\n'
        "# except * and match subject: are comments\n",
        encoding="utf-8",
    )
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": "==3.13.*"})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.COMPLETE
    assert result.status.diagnostics == ()


@pytest.mark.parametrize(
    ("target_python", "coverage_state"),
    (
        ("==3.13.*", AnalysisCoverageState.PARTIAL),
        ("==3.14.*", AnalysisCoverageState.COMPLETE),
    ),
)
def test_python_analyzer_classifies_real_template_strings_by_target(
    tmp_path: Path,
    target_python: str,
    coverage_state: AnalysisCoverageState,
) -> None:
    """Classify parsed template strings against the declared target.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.
    target_python : str
        Explicit Python target contract for the analyzer.
    coverage_state : codira.models.AnalysisCoverageState
        Expected analysis coverage state.

    Returns
    -------
    None
        The test asserts real t-strings remain target-version-sensitive.
    """
    source = tmp_path / "template.py"
    source.write_text('template = t"Hello {name}"\n', encoding="utf-8")
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": target_python})

    result = analyzer.analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is coverage_state
    if coverage_state is AnalysisCoverageState.PARTIAL:
        assert result.status.diagnostics[0].category == "target_version"
    else:
        assert result.status.diagnostics == ()


def test_python_analyzer_withholds_artifacts_for_invalid_matrix_fixture(
    tmp_path: Path,
) -> None:
    """Keep invalid matrix source as a partial analysis without artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts the fixture preserves the grammar-error contract.
    """
    source = tmp_path / "invalid.py"
    source.write_text(
        (_COMPATIBILITY_FIXTURE_ROOT / "invalid.py.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = PythonAnalyzer().analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.PARTIAL
    assert result.status.reliable_categories == ()
    assert result.documentation == ()
    assert result.index_symbols is False


def test_python_analyzer_withholds_artifacts_after_grammar_error(
    tmp_path: Path,
) -> None:
    """Withhold structural artifacts when Tree-sitter reports grammar errors.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts parser recovery does not create trustworthy symbols.
    """
    source = tmp_path / "broken.py"
    source.write_text("def broken(:\n    pass\n", encoding="utf-8")

    result = PythonAnalyzer().analyze_file(source, tmp_path)

    assert result.status is not None
    assert result.status.coverage_state is AnalysisCoverageState.PARTIAL
    assert result.status.reliable_categories == ()
    assert result.index_symbols is False


def test_python_package_declares_expected_entry_point() -> None:
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

    assert project["project"]["version"] == "2.0.0"
    assert project["project"]["dependencies"] == [
        "codira>=2.0.0,<3.0.0",
        "tree-sitter>=0.25.2",
        "tree-sitter-python>=0.25.0",
    ]
    assert project["project"]["entry-points"]["codira.analyzers"] == {
        "python": "codira_analyzer_python:build_analyzer"
    }


def test_python_package_builds_expected_analyzer() -> None:
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

    assert isinstance(analyzer, PythonAnalyzer)
    assert analyzer.name == "python"


def test_python_analyzer_applies_configuration_options(tmp_path: Path) -> None:
    """
    Apply Python analyzer artifact toggles and path filters.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured emission switches prune optional artifacts.
    """

    source = tmp_path / "src" / "pkg" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        '"""Module docs."""\n'
        "import os\n"
        "VALUE = 1\n"
        "Alias = int\n"
        "def run():\n"
        "    return os.name\n",
        encoding="utf-8",
    )
    excluded = tmp_path / "src" / "pkg" / "skip.py"
    excluded.write_text("VALUE = 2\n", encoding="utf-8")

    analyzer = PythonAnalyzer()
    schema = analyzer.configuration_json_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    analyzer.configure(
        {
            "include_paths": ["src/pkg"],
            "exclude_paths": ["src/pkg/skip.py"],
            "emit_module_documentation": False,
            "emit_imports": False,
            "emit_constants": False,
            "emit_type_aliases": False,
        }
    )

    result = analyzer.analyze_file(source, tmp_path)

    assert "emit_imports" in properties
    assert analyzer.allows_path(source, tmp_path) is True
    assert analyzer.allows_path(excluded, tmp_path) is False
    assert result.documentation == ()
    assert result.imports == ()
    assert result.declarations == ()


def test_python_analyzer_rebases_shadowed_module_file_stable_ids(
    tmp_path: Path,
) -> None:
    """
    Rebase stable IDs for module files shadowed by sibling packages.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts package ``__init__`` keeps the canonical import
        identity while the shadowed module file gets path-qualified identities.
    """
    module_file = tmp_path / "pkg" / "mod.py"
    package_init = tmp_path / "pkg" / "mod" / "__init__.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text(
        "class Tool:\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "def make():\n"
        "    return Tool()\n"
        "\n"
        "VALUE = 1\n",
        encoding="utf-8",
    )
    package_init.parent.mkdir(parents=True)
    package_init.write_text("PACKAGE_VALUE = 1\n", encoding="utf-8")

    analyzer = PythonAnalyzer()
    module_result = analyzer.analyze_file(module_file, tmp_path)
    package_result = analyzer.analyze_file(package_init, tmp_path)

    assert module_result.module.name == "pkg.mod"
    assert module_result.module.stable_id == "python:module:pkg.mod:path:pkg/mod.py"
    assert module_result.classes[0].stable_id == (
        "python:class:pkg.mod:path:pkg/mod.py:Tool"
    )
    assert module_result.classes[0].methods[0].stable_id == (
        "python:method:pkg.mod:path:pkg/mod.py:Tool.run"
    )
    assert module_result.functions[0].stable_id == (
        "python:function:pkg.mod:path:pkg/mod.py:make"
    )
    assert module_result.declarations[0].stable_id == (
        "python:constant:pkg.mod:path:pkg/mod.py:VALUE"
    )
    assert package_result.module.stable_id == "python:module:pkg.mod"
