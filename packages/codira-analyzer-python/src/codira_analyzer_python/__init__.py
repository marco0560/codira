"""Python language analyzer for codira.

Responsibilities
----------------
- Declare analyzer metadata such as name, version, and discovery globs.
- Parse Python files via `codira.parser_ast` and normalize them into
  `AnalysisResult` objects.
- Expose the package entry-point factory used by the plugin registry.

Design principles
-----------------
The analyzer isolates Python-specific parsing from storage concerns while
staying deterministic.

Architectural role
------------------
This module belongs to the **language analyzer layer** and implements the
first-party Python analyzer distribution for Phase 2 packaging.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer
    from codira.models import AnalysisResult

from codira.normalization import analysis_result_from_parsed
from codira.parser_ast import parse_file
from codira.contracts import AnalyzerCapabilityDeclaration

__all__ = ["PythonAnalyzer", "build_analyzer"]


class PythonAnalyzer:
    """
    Concrete Python analyzer for repository indexing.

    Parameters
    ----------
    None

    Notes
    -----
    This analyzer owns Python-specific parsing and normalization only. It does
    not own backend persistence or indexing policy.
    """

    name = "python"
    version = "2"
    discovery_globs: tuple[str, ...] = ("*.py",)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return Python analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from Python artifacts to canonical ontology types.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_python:build_analyzer",
            supports=("module", "type", "callable", "import"),
            does_not_support=("constant", "variable", "namespace"),
            mappings={
                "module": "module",
                "class": "type",
                "type_alias": "type",
                "function": "callable",
                "method": "callable",
                "import": "import",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a source path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the file is a Python source file.
        """
        return path.suffix == ".py"

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one Python source file into normalized artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Python source file to analyze.
        root : pathlib.Path
            Repository root used for module-name derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Normalized analysis result for the file.
        """
        return analysis_result_from_parsed(path, parse_file(path, root))


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party Python analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh Python analyzer instance for registry discovery.
    """
    return PythonAnalyzer()
