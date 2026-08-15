"""Resolve declared Python target versions independently from the host parser."""

from __future__ import annotations

import sys
import tomllib
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

if TYPE_CHECKING:
    from pathlib import Path


class TargetPythonOutcome(StrEnum):
    """Classify one target-version declaration resolution.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Members are serialized in capability and provenance payloads.
    """

    OVERRIDE = "override"
    DETECTED = "detected"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


SUPPORTED_TARGET_PYTHON_MINORS: tuple[str, ...] = (
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
)
"""Advertised target-minor vocabulary, backed by analyzer fixture validation."""

TESTED_TARGET_PYTHON_MINORS: tuple[str, ...] = (
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
)
"""Target minors with an explicit bundled-grammar fixture."""

PYTHON_TARGET_GRAMMAR = "tree-sitter-python-0.25.0"
"""Bundled grammar identity used by the first-party Python analyzer."""

PYTHON_TARGET_GRAMMAR_MAXIMUM_MINOR = "3.14"
"""Highest target minor covered by the bundled grammar fixtures."""


@dataclass(frozen=True)
class TargetPythonContract:
    """Describe one target Python declaration and its bounded normalization.

    Parameters
    ----------
    source : str
        ``override``, ``pyproject``, or ``none`` declaration source.
    specifier : str | None
        Original PEP 440 specifier when available.
    outcome : TargetPythonOutcome
        Deterministic resolution outcome.
    supported_minors : tuple[str, ...]
        Declared-minor vocabulary members selected by the specifier.
    host_python : str
        Host interpreter minor that runs Codira.
    parser_compatibility : str
        Explicit statement that target parsing is owned by the optional
        language analyzer package.
    detail : str | None
        Stable diagnostic for invalid or unsupported declarations.
    """

    source: str
    specifier: str | None
    outcome: TargetPythonOutcome
    supported_minors: tuple[str, ...]
    host_python: str
    parser_compatibility: str
    detail: str | None = None

    def payload(self) -> dict[str, object]:
        """Render a JSON-compatible target compatibility and provenance payload.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Deterministic data suitable for capability output.
        """
        value = asdict(self)
        value["outcome"] = self.outcome.value
        value["supported_minors"] = list(self.supported_minors)
        return value


def resolve_target_python_contract(
    root: Path,
    *,
    override: str | None = None,
) -> TargetPythonContract:
    """Resolve an override or ``[project].requires-python`` declaration.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing an optional ``pyproject.toml``.
    override : str | None, optional
        Explicit analyzer configuration that takes precedence over repository
        metadata.

    Returns
    -------
    TargetPythonContract
        Bounded target declaration independent from host parser support.
    """
    host_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    parser_compatibility = "plugin_owned_tree_sitter"
    if override is not None:
        return _normalize_specifier(
            override,
            source="override",
            host_python=host_python,
            parser_compatibility=parser_compatibility,
            override_selected=True,
        )
    detected = _read_requires_python(root)
    if detected is None:
        return TargetPythonContract(
            source="none",
            specifier=None,
            outcome=TargetPythonOutcome.UNKNOWN,
            supported_minors=(),
            host_python=host_python,
            parser_compatibility=parser_compatibility,
        )
    return _normalize_specifier(
        detected,
        source="pyproject",
        host_python=host_python,
        parser_compatibility=parser_compatibility,
        override_selected=False,
    )


def _read_requires_python(root: Path) -> str | None:
    """Read an optional ``[project].requires-python`` string without imports.

    Parameters
    ----------
    root : pathlib.Path
        Repository root to inspect.

    Returns
    -------
    str | None
        Declared specifier or ``None`` when metadata is absent or irrelevant.
    """
    path = root / "pyproject.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = document.get("project")
    if not isinstance(project, dict):
        return None
    value = project.get("requires-python")
    return value if isinstance(value, str) and value.strip() else None


def _normalize_specifier(
    specifier: str,
    *,
    source: str,
    host_python: str,
    parser_compatibility: str,
    override_selected: bool,
) -> TargetPythonContract:
    """Normalize one PEP 440 specifier against the declared minor vocabulary.

    Parameters
    ----------
    specifier : str
        Candidate PEP 440 version constraint.
    source : str
        Source identity for provenance.
    host_python : str
        Current host interpreter minor.
    parser_compatibility : str
        Current parser compatibility statement.
    override_selected : bool
        Whether explicit configuration supplied the declaration.

    Returns
    -------
    TargetPythonContract
        Deterministic normalized contract.
    """
    normalized = specifier.strip()
    try:
        constraints = SpecifierSet(normalized)
    except InvalidSpecifier as exc:
        return TargetPythonContract(
            source=source,
            specifier=normalized,
            outcome=TargetPythonOutcome.INVALID,
            supported_minors=(),
            host_python=host_python,
            parser_compatibility=parser_compatibility,
            detail=str(exc),
        )
    minors = tuple(
        minor
        for minor in SUPPORTED_TARGET_PYTHON_MINORS
        if Version(f"{minor}.0") in constraints
    )
    if not minors:
        return TargetPythonContract(
            source=source,
            specifier=normalized,
            outcome=TargetPythonOutcome.UNSUPPORTED,
            supported_minors=(),
            host_python=host_python,
            parser_compatibility=parser_compatibility,
            detail="specifier does not intersect Codira's declared target-minor vocabulary",
        )
    outcome = (
        TargetPythonOutcome.OVERRIDE
        if override_selected
        else (
            TargetPythonOutcome.PARTIAL
            if _is_partial(constraints)
            else TargetPythonOutcome.DETECTED
        )
    )
    return TargetPythonContract(
        source=source,
        specifier=normalized,
        outcome=outcome,
        supported_minors=minors,
        host_python=host_python,
        parser_compatibility=parser_compatibility,
    )


def _is_partial(specifier: SpecifierSet) -> bool:
    """Return whether a constraint is open ended or excludes target minors.

    Parameters
    ----------
    specifier : packaging.specifiers.SpecifierSet
        Valid parsed PEP 440 constraint.

    Returns
    -------
    bool
        ``True`` when normalization necessarily omits an open or excluded part.
    """
    values = tuple(specifier)
    has_upper = any(item.operator in {"<", "<=", "==", "~=", "==="} for item in values)
    return not has_upper or any(item.operator == "!=" for item in values)
