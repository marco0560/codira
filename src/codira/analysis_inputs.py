"""Coordinate analyzer-owned external input identities without resolving them.

Parameters
----------
None

Returns
-------
None
    Generic fingerprint validation and backend-neutral reader freshness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.contracts import (
    AnalysisInputFingerprintProvider,
    AnalysisInputReuseValidator,
    AnalysisInputStateBackend,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from codira.contracts import IndexBackend, LanguageAnalyzer


def analysis_input_fingerprint(
    analyzer: LanguageAnalyzer, path: Path, root: Path
) -> str:
    """Read an optional analyzer fingerprint while preserving source-only support.

    Parameters
    ----------
    analyzer : codira.contracts.LanguageAnalyzer
        Configured owner of the source path.
    path : pathlib.Path
        Source file being considered.
    root : pathlib.Path
        Repository resolution context.

    Returns
    -------
    str
        Nonempty declared input identity, or empty for source-only analyzers.

    Raises
    ------
    ValueError
        If the optional provider returns an empty or non-string identity.
    OSError
        If the provider cannot observe its required inputs.
    """
    if not isinstance(analyzer, AnalysisInputFingerprintProvider):
        return ""
    return validate_analysis_input_fingerprint(
        analyzer.analysis_input_fingerprint(path, root)
    )


def validate_analysis_input_fingerprint(value: str) -> str:
    """Validate an opaque identity at the external-input coordinator boundary.

    Parameters
    ----------
    value : str
        Identity supplied by an optional input provider.

    Returns
    -------
    str
        Validated nonempty identity without changing its representation.

    Raises
    ------
    ValueError
        If the supplied value is empty or not a string.
    """
    if not isinstance(value, str) or not value:
        message = "Analyzer returned an invalid analysis input fingerprint"
        raise ValueError(message)
    return value


def analysis_input_fingerprint_matches(
    analyzer: LanguageAnalyzer, path: Path, root: Path, expected: str
) -> bool:
    """Use an optional content-based validator or recompute the input identity.

    Parameters
    ----------
    analyzer : codira.contracts.LanguageAnalyzer
        Configured source owner.
    path : pathlib.Path
        Source path being checked.
    root : pathlib.Path
        Repository resolution context.
    expected : str
        Previously observed opaque input identity.

    Returns
    -------
    bool
        Whether the declared inputs remain equivalent to the captured identity.
    """
    if (
        isinstance(analyzer, AnalysisInputFingerprintProvider)
        and isinstance(analyzer, AnalysisInputReuseValidator)
        and analyzer.analysis_input_fingerprint_matches(path, root, expected)
    ):
        return True
    return analysis_input_fingerprint(analyzer, path, root) == expected


def analysis_inputs_changed(
    root: Path,
    backend: IndexBackend,
    analyzers: Sequence[LanguageAnalyzer],
    failures: Sequence[Mapping[str, str]] = (),
) -> bool:
    """Compare persisted external inputs for successful and failed source paths.

    Parameters
    ----------
    root : pathlib.Path
        Repository whose already-compatible index is inspected.
    backend : codira.contracts.IndexBackend
        Backend selected after physical-schema and inventory freshness checks.
    analyzers : collections.abc.Sequence[codira.contracts.LanguageAnalyzer]
        Configured analyzer owners with current resolution semantics.
    failures : collections.abc.Sequence[collections.abc.Mapping[str, str]], optional
        Retained failure rows with relative paths and attempted input identities.

    Returns
    -------
    bool
        Whether any observed dependency identity changed or became unavailable.

    Raises
    ------
    ValueError
        If an external-input analyzer uses a backend lacking persistence support.
    """
    providers = {
        str(item.name): item
        for item in analyzers
        if isinstance(item, AnalysisInputFingerprintProvider)
    }
    owners = backend.load_existing_file_ownership(root)
    names = {path: owner[0] for path, owner in owners.items()}
    names.update(
        (str(root / failure["path"]), failure["analyzer_name"]) for failure in failures
    )
    if not isinstance(backend, AnalysisInputStateBackend):
        if any(name in providers for name in names.values()):
            message = f"Backend {backend.name} cannot persist external analysis inputs"
            raise ValueError(message)
        return False
    stored = backend.load_existing_file_analysis_inputs(root)
    for failure in failures:
        path = str(root / failure["path"])
        names[path] = failure["analyzer_name"]
        stored[path] = failure.get("analysis_input_fingerprint", "")
    for path, owner in names.items():
        provider = providers.get(owner)
        try:
            unchanged = (
                stored.get(path, "") == ""
                if provider is None
                else analysis_input_fingerprint_matches(
                    provider, root / path, root, stored.get(path, "")
                )
            )
        except OSError:
            return True
        if not unchanged:
            return True
    return False
