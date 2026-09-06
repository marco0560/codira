"""Doxygen documentation artifact construction for the C++ analyzer.

Responsibilities
----------------
- Translate attached Doxygen text into stable documentation artifacts.
- Preserve deterministic ordering across module and declaration owners.

Architectural role
------------------
This module consumes normalized analysis results and comment attachment facts;
it neither parses C++ nor owns analyzer configuration.
"""

from __future__ import annotations

from pathlib import Path

from codira.models import AnalysisResult, DocumentationArtifact, DocumentationKind


def _documentation_artifact(
    *,
    path: Path,
    owner_stable_id: str,
    owner_kind: str,
    title: str,
    text: str,
    lineno: int,
    end_lineno: int | None,
    kind: DocumentationKind = "declaration",
) -> DocumentationArtifact:
    """
    Build one Doxygen documentation artifact for a C++ owner.

    Parameters
    ----------
    path : pathlib.Path
        Source file that owns the documentation artifact.
    owner_stable_id : str
        Stable identity of the documented owner.
    owner_kind : str
        Stable classifier of the documented owner.
    title : str
        Human-readable owner title.
    text : str
        Normalized Doxygen payload.
    lineno : int
        First Doxygen source line.
    end_lineno : int | None
        Inclusive final Doxygen source line when available.
    kind : codira.models.DocumentationKind, optional
        Documentation artifact kind.

    Returns
    -------
    codira.models.DocumentationArtifact
        Normalized documentation artifact for retrieval.
    """
    return DocumentationArtifact(
        stable_id=f"doc:{kind}:{owner_stable_id}:doxygen",
        kind=kind,
        source_format="doxygen",
        source_path=path,
        lineno=lineno,
        end_lineno=end_lineno,
        title=title,
        heading_path=(),
        text=text,
        owner_stable_id=owner_stable_id,
        owner_kind=owner_kind,
        attachment_confidence="explicit",
    )


def _append_attached_documentation_artifact(
    artifacts: list[DocumentationArtifact],
    *,
    path: Path,
    owner_stable_id: str,
    owner_kind: str,
    title: str,
    owner_lineno: int,
    doxygen_by_lineno: dict[int, tuple[str, int, int | None]],
) -> None:
    """
    Append one owner-attached Doxygen artifact when a match exists.

    Parameters
    ----------
    artifacts : list[codira.models.DocumentationArtifact]
        Mutable documentation artifact accumulator.
    path : pathlib.Path
        Source file that owns the documentation artifact.
    owner_stable_id : str
        Stable identity of the documented owner.
    owner_kind : str
        Stable classifier of the documented owner.
    title : str
        Human-readable owner title.
    owner_lineno : int
        Source line where the documented owner starts.
    doxygen_by_lineno : dict[int, tuple[str, int, int | None]]
        Attached Doxygen documentation keyed by owner start line.

    Returns
    -------
    None
        The accumulator is updated in place when documentation exists.
    """
    attached = doxygen_by_lineno.get(owner_lineno)
    if attached is None:
        return
    text, lineno, end_lineno = attached
    artifacts.append(
        _documentation_artifact(
            path=path,
            owner_stable_id=owner_stable_id,
            owner_kind=owner_kind,
            title=title,
            text=text,
            lineno=lineno,
            end_lineno=end_lineno,
        )
    )


def _documentation_artifacts(
    *,
    path: Path,
    analysis: AnalysisResult,
    module_doxygen: tuple[str, int, int | None] | None,
    doxygen_by_lineno: dict[int, tuple[str, int, int | None]],
) -> tuple[DocumentationArtifact, ...]:
    """
    Build C++ Doxygen documentation artifacts for module and declaration owners.

    Parameters
    ----------
    path : pathlib.Path
        C++ source path being analyzed.
    analysis : codira.models.AnalysisResult
        Analyzer result whose owners may have attached Doxygen documentation.
    module_doxygen : tuple[str, int, int | None] | None
        Leading Doxygen module documentation and source coordinates.
    doxygen_by_lineno : dict[int, tuple[str, int, int | None]]
        Attached Doxygen documentation keyed by owner start line.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        Deterministic Doxygen documentation artifacts.
    """
    artifacts: list[DocumentationArtifact] = []
    if module_doxygen is not None:
        text, lineno, end_lineno = module_doxygen
        artifacts.append(
            _documentation_artifact(
                path=path,
                owner_stable_id=analysis.module.stable_id,
                owner_kind="module",
                title=analysis.module.name,
                text=text,
                lineno=lineno,
                end_lineno=end_lineno,
                kind="module",
            )
        )

    for class_artifact in analysis.classes:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=class_artifact.stable_id,
            owner_kind="class",
            title=class_artifact.name,
            owner_lineno=class_artifact.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
        )
        for method in class_artifact.methods:
            _append_attached_documentation_artifact(
                artifacts,
                path=path,
                owner_stable_id=method.stable_id,
                owner_kind="method",
                title=method.name,
                owner_lineno=method.lineno,
                doxygen_by_lineno=doxygen_by_lineno,
            )

    for function in analysis.functions:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=function.stable_id,
            owner_kind="function",
            title=function.name,
            owner_lineno=function.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
        )

    for declaration in analysis.declarations:
        _append_attached_documentation_artifact(
            artifacts,
            path=path,
            owner_stable_id=declaration.stable_id,
            owner_kind=declaration.kind,
            title=declaration.name,
            owner_lineno=declaration.lineno,
            doxygen_by_lineno=doxygen_by_lineno,
        )

    return tuple(artifacts)
