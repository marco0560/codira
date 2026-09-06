"""Backend retrieval request records re-exported by :mod:`codira.contracts`.

The immutable records keep relation, candidate, score-resolution, and runtime
inventory inputs grouped independently from backend protocol definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer, SimilarityCandidate


@dataclass(frozen=True)
class BackendRelationQueryRequest:
    """
    Backend request for exact relation and include-edge lookup.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    name : str
        Exact logical or include-target name to search for.
    module : str | None, optional
        Optional module qualifier used to restrict results.
    incoming : bool, optional
        Whether to return incoming edges instead of outgoing edges.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict owner files.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    name: str
    module: str | None = None
    incoming: bool = False
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendEmbeddingCandidatesRequest:
    """
    Backend request for ranked embedding candidate lookup.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    query : str
        User query string.
    limit : int
        Maximum number of ranked results to return.
    min_score : float
        Minimum similarity threshold for emitted results.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched symbol files.
    search_profile : str | None, optional
        Named similarity-index runtime profile. ``None`` selects ``default``.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    query: str
    limit: int
    min_score: float
    prefix: str | None = None
    search_profile: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendDocumentationCandidatesRequest:
    """
    Backend request for ranked documentation candidate lookup.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose index should be queried.
    query : str
        User query string.
    limit : int
        Maximum number of ranked documentation results to return.
    min_score : float
        Minimum similarity threshold for emitted results.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched documents.
    search_profile : str | None, optional
        Named similarity-index runtime profile. ``None`` selects ``default``.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    query: str
    limit: int
    min_score: float
    prefix: str | None = None
    search_profile: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendResolveEmbeddingScoresRequest:
    """
    Backend request for resolving scored symbol stable IDs.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose structural index should be queried.
    candidates : collections.abc.Sequence[codira.contracts.SimilarityCandidate]
        Selected-index candidates keyed by symbol stable ID with provenance.
    limit : int
        Maximum number of resolved candidates to return.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched symbol files.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    candidates: Sequence[SimilarityCandidate]
    limit: int
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendResolveDocumentationScoresRequest:
    """
    Backend request for resolving scored documentation stable IDs.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose structural index should be queried.
    candidates : collections.abc.Sequence[codira.contracts.SimilarityCandidate]
        Selected-index candidates keyed by documentation stable ID with provenance.
    limit : int
        Maximum number of resolved candidates to return.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict matched document files.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    candidates: Sequence[SimilarityCandidate]
    limit: int
    prefix: str | None = None
    conn: object | None = None


@dataclass(frozen=True)
class BackendRuntimeInventoryRequest:
    """
    Backend request for persisting runtime inventory after indexing.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose backend state should be updated.
    backend_name : str
        Active backend name.
    backend_version : str
        Active backend version.
    coverage_complete : bool
        Whether canonical-directory coverage had no gaps.
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Active analyzers for the run.
    conn : object | None, optional
        Existing backend connection to reuse.
    """

    root: Path
    backend_name: str
    backend_version: str
    coverage_complete: bool
    analyzers: Sequence[LanguageAnalyzer]
    conn: object | None = None
