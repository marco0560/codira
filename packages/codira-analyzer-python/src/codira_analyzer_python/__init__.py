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

import tokenize
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer
    from codira.models import (
        AnalysisResult,
        ClassArtifact,
        FunctionArtifact,
    )

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.normalization import analysis_result_from_parsed
from codira.parser_ast import parse_source

__all__ = ["PythonAnalyzer", "build_analyzer"]

ArtifactT = TypeVar("ArtifactT")


def _read_python_source(path: Path) -> str:
    """
    Read one Python source file with PEP 263 encoding support.

    Parameters
    ----------
    path : pathlib.Path
        Python source file to decode.

    Returns
    -------
    str
        Decoded source text honoring the file's declared encoding.
    """
    with tokenize.open(path) as handle:
        return handle.read()


def _rewrite_colliding_stable_ids(
    artifacts: tuple[ArtifactT, ...],
    *,
    stable_id_getter: Callable[[ArtifactT], str],
    stable_id_setter: Callable[[ArtifactT, str], ArtifactT],
) -> tuple[ArtifactT, ...]:
    """
    Rewrite colliding stable IDs with deterministic ordinal suffixes.

    Parameters
    ----------
    artifacts : tuple[ArtifactT, ...]
        Artifacts to inspect in deterministic source order.
    stable_id_getter : collections.abc.Callable[[ArtifactT], str]
        Accessor returning the current stable ID for one artifact.
    stable_id_setter : collections.abc.Callable[[ArtifactT, str], ArtifactT]
        Rebuilder returning one artifact with a rewritten stable ID.

    Returns
    -------
    tuple[ArtifactT, ...]
        Artifacts with colliding stable IDs rewritten as ``:1``, ``:2``, and
        so on, while unique stable IDs remain unchanged.
    """
    counts = Counter(stable_id_getter(artifact) for artifact in artifacts)
    if all(count == 1 for count in counts.values()):
        return artifacts

    seen: dict[str, int] = {}
    rewritten: list[ArtifactT] = []
    for artifact in artifacts:
        stable_id = stable_id_getter(artifact)
        if counts[stable_id] == 1:
            rewritten.append(artifact)
            continue
        seen[stable_id] = seen.get(stable_id, 0) + 1
        rewritten.append(stable_id_setter(artifact, f"{stable_id}:{seen[stable_id]}"))
    return tuple(rewritten)


def _replace_function_stable_id(
    function: FunctionArtifact,
    stable_id: str,
) -> FunctionArtifact:
    """
    Replace one function or method stable ID and rebind overload parents.

    Parameters
    ----------
    function : codira.models.FunctionArtifact
        Function-like artifact to rewrite.
    stable_id : str
        New stable ID for the function or method.

    Returns
    -------
    codira.models.FunctionArtifact
        Function artifact with the updated stable ID and overload parents.
    """
    overloads = tuple(
        replace(overload, parent_stable_id=stable_id) for overload in function.overloads
    )
    return replace(function, stable_id=stable_id, overloads=overloads)


def _disambiguate_overload_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Rewrite colliding overload stable IDs while preserving parent order.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Canonical callables whose overloads should be inspected.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Functions with overload stable IDs rewritten only when collisions are
        present.
    """
    overload_counts = tuple(len(function.overloads) for function in functions)
    overloads = tuple(
        overload for function in functions for overload in function.overloads
    )
    rewritten_overloads = _rewrite_colliding_stable_ids(
        overloads,
        stable_id_getter=lambda overload: overload.stable_id,
        stable_id_setter=lambda overload, stable_id: replace(
            overload,
            stable_id=stable_id,
        ),
    )
    if rewritten_overloads == overloads:
        return functions

    rewritten_functions: list[FunctionArtifact] = []
    cursor = 0
    for function, overload_count in zip(functions, overload_counts, strict=True):
        rewritten_functions.append(
            replace(
                function,
                overloads=rewritten_overloads[cursor : cursor + overload_count],
            )
        )
        cursor += overload_count
    return tuple(rewritten_functions)


def _disambiguate_function_stable_ids(
    functions: tuple[FunctionArtifact, ...],
) -> tuple[FunctionArtifact, ...]:
    """
    Rewrite colliding function or method stable IDs deterministically.

    Parameters
    ----------
    functions : tuple[codira.models.FunctionArtifact, ...]
        Function-like artifacts in deterministic source order.

    Returns
    -------
    tuple[codira.models.FunctionArtifact, ...]
        Functions with colliding stable IDs rewritten, including overload
        parent bindings.
    """
    rewritten_functions = _rewrite_colliding_stable_ids(
        functions,
        stable_id_getter=lambda function: function.stable_id,
        stable_id_setter=_replace_function_stable_id,
    )
    return _disambiguate_overload_stable_ids(rewritten_functions)


def _disambiguate_method_stable_ids(
    classes: tuple[ClassArtifact, ...],
) -> tuple[ClassArtifact, ...]:
    """
    Rewrite colliding method stable IDs across all classes in one file.

    Parameters
    ----------
    classes : tuple[codira.models.ClassArtifact, ...]
        Class artifacts in deterministic source order.

    Returns
    -------
    tuple[codira.models.ClassArtifact, ...]
        Classes with rewritten method stable IDs when collisions are present.
    """
    method_counts = tuple(len(class_artifact.methods) for class_artifact in classes)
    methods = tuple(
        method for class_artifact in classes for method in class_artifact.methods
    )
    rewritten_methods = _disambiguate_function_stable_ids(methods)
    if rewritten_methods == methods:
        return classes

    rewritten_classes: list[ClassArtifact] = []
    cursor = 0
    for class_artifact, method_count in zip(classes, method_counts, strict=True):
        rewritten_classes.append(
            replace(
                class_artifact,
                methods=rewritten_methods[cursor : cursor + method_count],
            )
        )
        cursor += method_count
    return tuple(rewritten_classes)


def _disambiguate_analysis_stable_ids(analysis: AnalysisResult) -> AnalysisResult:
    """
    Enforce analyzer-owned stable ID uniqueness within one Python result.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized Python analyzer output.

    Returns
    -------
    codira.models.AnalysisResult
        Analysis result with deterministic suffixes added only for colliding
        classes, functions, methods, declarations, and overloads.
    """
    classes = _rewrite_colliding_stable_ids(
        analysis.classes,
        stable_id_getter=lambda class_artifact: class_artifact.stable_id,
        stable_id_setter=lambda class_artifact, stable_id: replace(
            class_artifact,
            stable_id=stable_id,
        ),
    )
    classes = _disambiguate_method_stable_ids(classes)
    functions = _disambiguate_function_stable_ids(analysis.functions)
    declarations = _rewrite_colliding_stable_ids(
        analysis.declarations,
        stable_id_getter=lambda declaration: declaration.stable_id,
        stable_id_setter=lambda declaration, stable_id: replace(
            declaration,
            stable_id=stable_id,
        ),
    )
    if (
        classes == analysis.classes
        and functions == analysis.functions
        and declarations == analysis.declarations
    ):
        return analysis
    return replace(
        analysis,
        classes=classes,
        functions=functions,
        declarations=declarations,
    )


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
    version = "4"
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
            supports=("module", "type", "callable", "import", "constant"),
            does_not_support=("variable", "namespace"),
            mappings={
                "module": "module",
                "class": "type",
                "type_alias": "type",
                "constant": "constant",
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
        source = _read_python_source(path)
        analysis = analysis_result_from_parsed(path, parse_source(path, root, source))
        return _disambiguate_analysis_stable_ids(analysis)


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
