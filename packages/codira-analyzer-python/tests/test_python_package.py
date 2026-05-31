"""Package-local tests for the first-party Python analyzer distribution."""

from __future__ import annotations

import tomllib
from pathlib import Path

from codira_analyzer_python import PythonAnalyzer, build_analyzer


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

    assert project["project"]["version"] == "1.5.4"
    assert project["project"]["dependencies"] == ["codira>=1.5.0,<2.0.0"]
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
