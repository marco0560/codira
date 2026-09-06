"""Scanner contract scenarios extracted from the ADR-004 suite."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from codira_analyzer_c import CAnalyzer
from codira_analyzer_python import PythonAnalyzer

from codira.models import AnalysisResult, ModuleArtifact
from codira.scanner import (
    discovery_file_globs,
    iter_canonical_project_files,
    iter_project_files,
)

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer


class _FakeAnalyzer:
    """Small analyzer stub used to validate the protocol surface."""

    name = "fake-python"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def supports_path(self, path: Path) -> bool:
        """
        Report support for Python files.

        Parameters
        ----------
        path : pathlib.Path
            Candidate source path.

        Returns
        -------
        bool
            ``True`` for Python files.
        """
        return path.suffix == ".py"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one file through the existing Python parser path.

        Parameters
        ----------
        path : pathlib.Path
            Source file to analyze.
        root : pathlib.Path
            Repository root used for module resolution.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        return PythonAnalyzer().analyze_file(path, root)


def test_discovery_file_globs_follow_analyzer_registration_order() -> None:
    """
    Derive deterministic scanner globs from analyzer metadata.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts analyzer-registration order is preserved while
        duplicate globs are removed.
    """
    analyzers: list[LanguageAnalyzer] = [PythonAnalyzer(), CAnalyzer(), _FakeAnalyzer()]

    assert discovery_file_globs(analyzers) == ("*.py", "*.c", "*.h")


def test_iter_project_files_uses_analyzer_declared_globs(tmp_path: Path) -> None:
    """
    Discover files through analyzer-declared globs outside Git repositories.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts scanner discovery is not limited to the former
        hard-coded core glob tuple.
    """

    class _DemoAnalyzer:
        name = "demo"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.demo",)

        def supports_path(self, path: Path) -> bool:
            return path.suffix == ".demo"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"demo:module:{path.stem}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    demo_file = tmp_path / "src" / "sample.demo"
    ignored_file = tmp_path / "src" / "sample.py"
    demo_file.parent.mkdir()
    demo_file.write_text("demo\n", encoding="utf-8")
    ignored_file.write_text("print('ignored')\n", encoding="utf-8")

    discovered = list(iter_project_files(tmp_path, analyzers=[_DemoAnalyzer()]))

    assert discovered == [demo_file]


def test_iter_project_files_uses_analyzer_globs_with_git(tmp_path: Path) -> None:
    """
    Discover tracked files through analyzer-declared globs inside Git repos.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts Git-backed discovery follows analyzer metadata.
    """

    class _DemoAnalyzer:
        name = "demo"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.demo",)

        def supports_path(self, path: Path) -> bool:
            return path.suffix == ".demo"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"demo:module:{path.stem}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    demo_file = tmp_path / "src" / "sample.demo"
    other_file = tmp_path / "src" / "sample.py"
    demo_file.parent.mkdir()
    demo_file.write_text("demo\n", encoding="utf-8")
    other_file.write_text("print('ignored')\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/sample.demo", "src/sample.py"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    discovered = list(iter_project_files(tmp_path, analyzers=[_DemoAnalyzer()]))

    assert discovered == [demo_file]


def test_iter_project_files_rejects_tracked_symlinks_outside_repository(
    tmp_path: Path,
) -> None:
    """
    Reject tracked source symlinks before analyzer reads can follow them.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts a supported tracked symlink targeting an external
        file is excluded from discovery.
    """

    class _DemoAnalyzer:
        name = "demo"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.demo",)

        def supports_path(self, path: Path) -> bool:
            return path.suffix == ".demo"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"demo:module:{path.stem}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    external_file = tmp_path.parent / f"{tmp_path.name}-external.demo"
    external_file.write_text("private content\n", encoding="utf-8")
    symlink = tmp_path / "leak.demo"
    symlink.symlink_to(external_file)
    subprocess.run(
        ["git", "add", "leak.demo"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    assert list(iter_project_files(tmp_path, analyzers=[_DemoAnalyzer()])) == []


def test_iter_project_files_filters_broad_globs_by_supports_path(
    tmp_path: Path,
) -> None:
    """
    Filter broad discovery globs through analyzer ownership checks.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts broad globs do not force unsupported files into the
        indexing set.
    """

    class _SelectiveJsonAnalyzer:
        name = "selective-json"
        version = "1"
        discovery_globs: tuple[str, ...] = ("*.json",)

        def supports_path(self, path: Path) -> bool:
            return path.name == "package.json"

        def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
            del root
            return AnalysisResult(
                source_path=path,
                module=ModuleArtifact(
                    name=path.stem,
                    stable_id=f"json:module:{path.name}",
                    docstring=None,
                    has_docstring=0,
                ),
                classes=(),
                functions=(),
                declarations=(),
                imports=(),
            )

    package_file = tmp_path / "package.json"
    lockfile = tmp_path / "package-lock.json"
    package_file.write_text('{"name": "demo"}\n', encoding="utf-8")
    lockfile.write_text('{"name": "demo"}\n', encoding="utf-8")

    discovered = list(
        iter_project_files(tmp_path, analyzers=[_SelectiveJsonAnalyzer()])
    )

    assert discovered == [package_file]


def test_iter_canonical_project_files_uses_git_tracked_directories(
    tmp_path: Path,
) -> None:
    """
    Discover tracked files under canonical directories through Git.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts canonical-directory discovery does not depend on the
        active analyzer set.
    """
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    src_file = tmp_path / "src" / "main.rs"
    test_file = tmp_path / "tests" / "test_main.py"
    docs_file = tmp_path / "docs" / "notes.md"
    src_file.parent.mkdir()
    test_file.parent.mkdir()
    docs_file.parent.mkdir()
    src_file.write_text("fn main() {}\n", encoding="utf-8")
    test_file.write_text("def test_demo():\n    pass\n", encoding="utf-8")
    docs_file.write_text("# ignored\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "src/main.rs", "tests/test_main.py", "docs/notes.md"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    discovered = list(iter_canonical_project_files(tmp_path))

    assert discovered == [src_file, test_file]
