"""Tests for independent target Python declaration resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from codira.capabilities import build_capability_contract
from codira.target_python import (
    PYTHON_TARGET_GRAMMAR,
    PYTHON_TARGET_GRAMMAR_MAXIMUM_MINOR,
    TESTED_TARGET_PYTHON_MINORS,
    TargetPythonOutcome,
    resolve_target_python_contract,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_project(root: Path, requires_python: str) -> None:
    """Write minimal project metadata carrying one target declaration.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root.
    requires_python : str
        PEP 440 ``[project].requires-python`` value.

    Returns
    -------
    None
        The project metadata is written for target detection.
    """
    root.joinpath("pyproject.toml").write_text(
        f'[project]\nname = "sample"\nrequires-python = "{requires_python}"\n',
        encoding="utf-8",
    )


def test_target_python_override_wins_over_project_metadata(tmp_path: Path) -> None:
    """Prefer explicit analyzer configuration over repository metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts override source and normalized target selection.
    """
    _write_project(tmp_path, ">=3.13")

    contract = resolve_target_python_contract(tmp_path, override="==3.9.*")

    assert contract.source == "override"
    assert contract.outcome is TargetPythonOutcome.OVERRIDE
    assert contract.supported_minors == ("3.9",)
    assert contract.parser_compatibility == "plugin_owned_tree_sitter"


def test_target_python_normalizes_bounded_open_and_excluded_specifiers(
    tmp_path: Path,
) -> None:
    """Classify bounded, open, and excluded declarations deterministically.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts bounded declarations are complete while open or
        excluded declarations remain explicitly partial.
    """
    _write_project(tmp_path, ">=3.9,<3.11")
    bounded = resolve_target_python_contract(tmp_path)
    assert bounded.outcome is TargetPythonOutcome.DETECTED
    assert bounded.supported_minors == ("3.9", "3.10")

    _write_project(tmp_path, ">=3.12")
    open_ended = resolve_target_python_contract(tmp_path)
    assert open_ended.outcome is TargetPythonOutcome.PARTIAL
    assert open_ended.supported_minors == ("3.12", "3.13", "3.14")

    _write_project(tmp_path, ">=3.8,!=3.9.*,<3.11")
    excluded = resolve_target_python_contract(tmp_path)
    assert excluded.outcome is TargetPythonOutcome.PARTIAL
    assert excluded.supported_minors == ("3.8", "3.10")


def test_target_python_reports_invalid_unknown_and_unsupported_outcomes(
    tmp_path: Path,
) -> None:
    """Keep malformed, absent, and disjoint declarations distinguishable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts each non-success outcome carries no target claim.
    """
    unknown = resolve_target_python_contract(tmp_path)
    assert unknown.outcome is TargetPythonOutcome.UNKNOWN
    assert unknown.supported_minors == ()

    _write_project(tmp_path, "not-a-specifier")
    invalid = resolve_target_python_contract(tmp_path)
    assert invalid.outcome is TargetPythonOutcome.INVALID
    assert invalid.supported_minors == ()

    _write_project(tmp_path, "<3.8")
    unsupported = resolve_target_python_contract(tmp_path)
    assert unsupported.outcome is TargetPythonOutcome.UNSUPPORTED
    assert unsupported.supported_minors == ()


def test_capabilities_expose_host_and_target_compatibility_separately(
    tmp_path: Path,
) -> None:
    """Expose target metadata without claiming host parser compatibility.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts capability output retains the host-AST limitation.
    """
    _write_project(tmp_path, ">=3.11,<3.13")

    payload = build_capability_contract(root=tmp_path)
    target = cast("dict[str, object]", payload["python_target"])

    assert target["source"] == "pyproject"
    assert target["outcome"] == "detected"
    assert target["supported_minors"] == ["3.11", "3.12"]
    assert target["parser_compatibility"] == "plugin_owned_tree_sitter"
    assert target["tested_minors"] == [
        "3.8",
        "3.9",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    ]
    assert target["tested_minors"] == list(TESTED_TARGET_PYTHON_MINORS)
    assert target["grammar"] == {
        "identity": PYTHON_TARGET_GRAMMAR,
        "maximum_target_minor": PYTHON_TARGET_GRAMMAR_MAXIMUM_MINOR,
    }
    assert target["feature_rules"] == [
        {"feature": "match_statement", "minimum_version": "3.10"},
        {"feature": "except_star", "minimum_version": "3.11"},
        {"feature": "type_alias_statement", "minimum_version": "3.12"},
        {"feature": "template_string", "minimum_version": "3.14"},
    ]
    provenance = cast("dict[str, object]", target["provenance"])
    assert provenance == {"source": "pyproject", "key": "project.requires-python"}


def test_capabilities_read_explicit_python_analyzer_override(tmp_path: Path) -> None:
    """Apply the configured analyzer override before project metadata.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts capability resolution reads the documented config key.
    """
    _write_project(tmp_path, ">=3.13")
    config_directory = tmp_path / ".codira"
    config_directory.mkdir()
    config_directory.joinpath("config.toml").write_text(
        '[plugins.analyzer-python]\ntarget_python = "==3.9.*"\n',
        encoding="utf-8",
    )

    payload = build_capability_contract(root=tmp_path)
    target = cast("dict[str, object]", payload["python_target"])

    assert target["source"] == "override"
    assert target["outcome"] == "override"
    assert target["supported_minors"] == ["3.9"]
