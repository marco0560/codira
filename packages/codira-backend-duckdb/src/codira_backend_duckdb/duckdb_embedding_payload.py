"""Deterministic embedding payload helpers for the DuckDB backend."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codira.models import AnalysisResult, FunctionArtifact

    from .duckdb_support import EmbeddingTextRequest


def _embedding_text(request: EmbeddingTextRequest) -> str:
    """
    Build the deterministic text payload embedded for one symbol.

    Parameters
    ----------
    request : EmbeddingTextRequest
        Embedding text construction request.

    Returns
    -------
    str
        Joined text payload used for embedding generation.
    """
    parts = [request.symbol_type, request.module_name, request.symbol_name]
    if request.signature:
        parts.append(request.signature)
    if request.docstring:
        parts.append(request.docstring)
    parts.extend(line for line in request.extra_context if line)
    return "\n".join(parts)


def _embedding_content_hash(text: str) -> str:
    """
    Return the deterministic content hash for one embedding payload.

    Parameters
    ----------
    text : str
        Exact semantic payload used for embedding generation.

    Returns
    -------
    str
        Hex-encoded SHA-256 digest of ``text``.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _c_embedding_context(analysis: AnalysisResult) -> tuple[str, ...]:
    """
    Build extra semantic context lines for C-family embedding payloads.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one indexed source file.

    Returns
    -------
    tuple[str, ...]
        Deterministic C-specific semantic context lines.
    """
    if analysis.source_path.suffix.lower() not in {".c", ".h"}:
        return ()
    context: list[str] = []
    if analysis.module.docstring:
        context.append(f"module summary: {analysis.module.docstring}")
    local_includes = tuple(
        imp.name for imp in analysis.imports if imp.kind == "include_local"
    )
    system_includes = tuple(
        imp.name for imp in analysis.imports if imp.kind == "include_system"
    )
    if local_includes:
        context.append("local includes: " + ", ".join(local_includes))
    if system_includes:
        context.append("system includes: " + ", ".join(system_includes))
    source_path = analysis.source_path
    suffix = source_path.suffix.lower()
    paired_path: Path | None = None
    if suffix == ".c":
        candidate = source_path.with_suffix(".h")
        if candidate.exists():
            paired_path = candidate
    elif suffix == ".h":
        candidate = source_path.with_suffix(".c")
        if candidate.exists():
            paired_path = candidate
    if paired_path is not None:
        pair_label = "paired header" if suffix == ".c" else "paired source"
        try:
            pair_rel_path = paired_path.relative_to(source_path.parents[1])
        except ValueError:
            pair_rel_path = paired_path
        context.append(f"{pair_label}: {pair_rel_path.as_posix()}")
    return tuple(context)


def _python_embedding_context(
    analysis: AnalysisResult,
    function: FunctionArtifact,
    *,
    class_name: str | None = None,
) -> tuple[str, ...]:
    """
    Build extra semantic context lines for Python callable embedding payloads.

    Parameters
    ----------
    analysis : codira.models.AnalysisResult
        Normalized analyzer output for one indexed source file.
    function : codira.models.FunctionArtifact
        Function or method artifact receiving the embedding payload.
    class_name : str | None, optional
        Owning class name for method artifacts.

    Returns
    -------
    tuple[str, ...]
        Deterministic Python-specific semantic context lines.
    """
    if analysis.source_path.suffix.lower() != ".py":
        return ()
    context: list[str] = []
    if analysis.module.docstring:
        context.append(f"module summary: {analysis.module.docstring}")
    if class_name is not None:
        context.append(f"owner class: {class_name}")
    if function.has_asserts:
        context.append("assertions: present")
    decorators = function.decorators
    if decorators:
        context.append("decorators: " + ", ".join(decorators))
    if any(name in {"fixture", "pytest.fixture"} for name in decorators):
        context.append("fixture context: pytest fixture")
    if function.name in {
        "setup",
        "setUp",
        "setup_class",
        "setup_method",
        "setup_function",
        "tearDown",
        "teardown",
        "teardown_class",
        "teardown_method",
        "teardown_function",
    }:
        context.append(f"setup context: {function.name}")
    return tuple(context)
