"""Tests for NumPy docstring validation helpers.

Responsibilities
----------------
- Confirm required sections adjust based on callable metadata (returns vs yields vs raises).
- Ensure unexpected sections are flagged for generators or regular functions.

Design principles
-----------------
Tests focus on deterministic docstring validation behavior without nondeterministic fixtures.

Architectural role
------------------
This module belongs to the **docstring verification layer** that keeps docstring hygiene consistent for analyzers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from codira.config import override_repo_config_path
from codira.docstring import (
    DocstringValidationRequest,
    find_missing_sections,
    find_unexpected_sections,
    validate_docstring,
    validate_documentation_with_configured_plugin,
)
from codira.registry import reset_plugin_registry_caches

if TYPE_CHECKING:
    from pathlib import Path


def _validation_request(
    doc: str | None,
    *,
    is_public: int,
    parameters: list[str] | None = None,
    require_callable_sections: bool = False,
    yields_value: bool = False,
    returns_value: bool = False,
    raises_exception: bool = False,
) -> DocstringValidationRequest:
    """
    Build a docstring-validation request for focused unit tests.

    Parameters
    ----------
    doc : str | None
        Docstring text under test.
    is_public : int
        Public visibility flag passed to the validator.
    parameters : list[str] | None, optional
        Callable parameters expected in the docstring.
    require_callable_sections : bool, optional
        Whether callable-specific sections are required.
    yields_value : bool, optional
        Whether the callable yields values.
    returns_value : bool, optional
        Whether the callable returns values.
    raises_exception : bool, optional
        Whether the callable raises exceptions.

    Returns
    -------
    DocstringValidationRequest
        Request object accepted by ``validate_docstring``.
    """
    return DocstringValidationRequest(
        doc=doc,
        is_public=is_public,
        parameters=parameters or [],
        require_callable_sections=require_callable_sections,
        yields_value=yields_value,
        returns_value=returns_value,
        raises_exception=raises_exception,
    )


def test_find_missing_sections_respects_callable_metadata() -> None:
    """
    Ensure required and conditional sections depend on callable metadata.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts section requirements derived from callable metadata.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.
    """

    missing = find_missing_sections(
        doc,
        require_parameters_section=True,
        require_returns_section=True,
        raises_exception=True,
    )

    assert missing == ["Returns", "Raises"]


def test_find_missing_sections_requires_yields_for_generators() -> None:
    """
    Ensure generator metadata requires a ``Yields`` section instead of ``Returns``.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts generator-specific section enforcement.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.
    """

    missing = find_missing_sections(
        doc,
        require_parameters_section=True,
        require_yields_section=True,
    )

    assert missing == ["Yields"]


def test_find_unexpected_sections_rejects_yields_for_regular_functions() -> None:
    """
    Ensure regular functions do not accept a ``Yields`` section.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that ``Yields`` is rejected for non-generators.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Returns
    -------
    int
        Result value.

    Yields
    ------
    int
        Unexpected iteration value.
    """

    unexpected = find_unexpected_sections(
        doc,
        allow_returns_section=True,
        allow_yields_section=False,
    )

    assert unexpected == ["Yields"]


def test_find_unexpected_sections_rejects_returns_for_pure_generators() -> None:
    """
    Ensure pure generators do not accept a ``Returns`` section.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that ``Returns`` is rejected without a terminal value.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Yields
    ------
    int
        Produced iteration value.

    Returns
    -------
    int
        Unexpected terminal value.
    """

    unexpected = find_unexpected_sections(
        doc,
        allow_returns_section=False,
        allow_yields_section=True,
    )

    assert unexpected == ["Returns"]


def test_validate_docstring_reports_missing_parameter_entry() -> None:
    """
    Ensure all declared parameters must appear in the Parameters section.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that undocumented parameters are reported.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Returns
    -------
    int
        Result value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x", "y"],
            require_callable_sections=True,
        )
    )

    assert ("missing_parameter", "Parameter not documented: y") in issues


def test_documentation_audit_requires_explicit_route(tmp_path: Path) -> None:
    """
    Skip documentation audit execution when no explicit route is configured.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts compatibility mode requires an explicit route.
    """

    source_path = tmp_path / "src" / "sample.py"
    source_path.parent.mkdir()
    source_path.write_text("def f(x):\n    return x\n", encoding="utf-8")

    issues = validate_documentation_with_configured_plugin(
        root=tmp_path,
        source_path=source_path,
        stable_id="py:function:f",
        symbol_name="f",
        artifact_kind="function",
        label="Function f",
        doc=None,
        is_public=1,
    )

    assert issues == []


def test_documentation_audit_routes_numpy_plugin(tmp_path: Path) -> None:
    """
    Route Python artifacts to the NumPy documentation audit plugin.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured NumPy routes emit validator diagnostics.
    """

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "python", convention = "numpy", plugin = "numpy", include_paths = ["src/**"] },
]
""".strip(),
        encoding="utf-8",
    )
    source_path = tmp_path / "src" / "sample.py"
    source_path.parent.mkdir()
    source_path.write_text("def f(x):\n    return x\n", encoding="utf-8")

    reset_plugin_registry_caches()
    with override_repo_config_path(config_path):
        issues = validate_documentation_with_configured_plugin(
            root=tmp_path,
            source_path=source_path,
            stable_id="py:function:f",
            symbol_name="f",
            artifact_kind="function",
            label="Function f",
            doc="Summary.",
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            returns_value=True,
        )

    assert ("non_numpy", "Function f: Docstring not in NumPy style") in issues


def test_documentation_audit_routes_doxygen_plugin(tmp_path: Path) -> None:
    """
    Route C artifacts to the Doxygen documentation audit plugin.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        The test asserts configured Doxygen routes emit diagnostics.
    """

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "c", convention = "doxygen", plugin = "doxygen", include_paths = ["src/**"] },
]
""".strip(),
        encoding="utf-8",
    )
    source_path = tmp_path / "src" / "sample.c"
    source_path.parent.mkdir()
    source_path.write_text("int f(void) { return 1; }\n", encoding="utf-8")

    reset_plugin_registry_caches()
    with override_repo_config_path(config_path):
        issues = validate_documentation_with_configured_plugin(
            root=tmp_path,
            source_path=source_path,
            stable_id="c:function:f",
            symbol_name="f",
            artifact_kind="function",
            label="Function f",
            doc=None,
            is_public=1,
        )

    assert issues == [("missing_doxygen", "Function f: Missing Doxygen documentation")]


def test_documentation_audit_routes_rustdoc_plugin(tmp_path: Path) -> None:
    """Route Rust artifacts to the Rustdoc documentation audit plugin.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Missing Rustdocs receive the convention-specific routed diagnostic.
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "rust", convention = "rustdoc", plugin = "rustdoc", include_paths = ["src/**"] },
]
""".strip(),
        encoding="utf-8",
    )
    source_path = tmp_path / "src" / "lib.rs"
    source_path.parent.mkdir()
    source_path.write_text("pub fn run() {}\n", encoding="utf-8")

    reset_plugin_registry_caches()
    with override_repo_config_path(config_path):
        issues = validate_documentation_with_configured_plugin(
            root=tmp_path,
            source_path=source_path,
            stable_id="rust:function:src/lib.rs:run",
            symbol_name="run",
            artifact_kind="function",
            label="Function run",
            doc=None,
            is_public=1,
        )

    assert issues == [
        ("missing_rustdoc", "Function run: Missing Rustdoc documentation")
    ]


def test_documentation_audit_routes_skip_private_rust_artifacts(tmp_path: Path) -> None:
    """Keep private Rust items outside configured documentation audits.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary repository root.

    Returns
    -------
    None
        Private Rust items do not produce missing-Rustdoc diagnostics.
    """
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[plugins]
documentation_audit_routes = [
  { language = "rust", convention = "rustdoc", plugin = "rustdoc", include_paths = ["src/**"] },
]
""".strip(),
        encoding="utf-8",
    )
    source_path = tmp_path / "src" / "lib.rs"
    source_path.parent.mkdir()
    source_path.write_text("fn private_helper() {}\n", encoding="utf-8")

    reset_plugin_registry_caches()
    with override_repo_config_path(config_path):
        issues = validate_documentation_with_configured_plugin(
            root=tmp_path,
            source_path=source_path,
            stable_id="rust:function:src/lib.rs:private_helper",
            symbol_name="private_helper",
            artifact_kind="function",
            label="Function private_helper",
            doc=None,
            is_public=0,
        )

    assert issues == []


def test_validate_docstring_reports_malformed_section_heading() -> None:
    """
    Ensure malformed NumPy section headings are detected.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that malformed headings are reported.
    """
    doc = """
    Summary.

    Parameters
    x : int
        Input value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
        )
    )

    assert (
        "malformed_section",
        "Malformed NumPy section heading: Parameters",
    ) in issues


def test_validate_docstring_requires_raises_only_when_explicit_raise_exists() -> None:
    """
    Ensure missing Raises is only reported for callables with explicit raises.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts conditional ``Raises`` enforcement.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Returns
    -------
    int
        Result value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            raises_exception=True,
        )
    )

    assert ("missing_section", "Missing section: Raises") in issues


def test_validate_docstring_requires_yields_for_generators() -> None:
    """
    Ensure generators require ``Yields`` instead of ``Returns``.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts generator-specific result-section enforcement.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            yields_value=True,
        )
    )

    assert ("missing_section", "Missing section: Yields") in issues
    assert ("missing_section", "Missing section: Returns") not in issues


def test_validate_docstring_rejects_yields_for_regular_functions() -> None:
    """
    Ensure regular functions reject a ``Yields`` section.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts semantic rejection of ``Yields`` for non-generators.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Returns
    -------
    int
        Result value.

    Yields
    ------
    int
        Unexpected iteration value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            returns_value=True,
        )
    )

    assert ("unexpected_section", "Unexpected section: Yields") in issues


def test_validate_docstring_rejects_returns_for_pure_generators() -> None:
    """
    Ensure pure generators reject a ``Returns`` section.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts semantic rejection of ``Returns`` for pure generators.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Yields
    ------
    int
        Produced iteration value.

    Returns
    -------
    int
        Unexpected terminal value.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            yields_value=True,
        )
    )

    assert ("unexpected_section", "Unexpected section: Returns") in issues


def test_validate_docstring_allows_returns_for_generators_with_terminal_value() -> None:
    """
    Ensure generators with terminal values may document both sections.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that terminal generator returns may be documented.
    """
    doc = """
    Summary.

    Parameters
    ----------
    x : int
        Input value.

    Yields
    ------
    int
        Produced iteration value.

    Returns
    -------
    int
        Terminal value exposed via ``StopIteration.value``.
    """

    issues = validate_docstring(
        _validation_request(
            doc,
            is_public=1,
            parameters=["x"],
            require_callable_sections=True,
            yields_value=True,
            returns_value=True,
        )
    )

    assert ("unexpected_section", "Unexpected section: Returns") not in issues


def test_validate_docstring_skips_private_missing_docstrings() -> None:
    """
    Ensure private callables are allowed to omit docstrings.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that private callables are exempt from missing
        docstring errors.
    """
    assert validate_docstring(_validation_request(None, is_public=0)) == []


def test_validate_docstring_allows_summary_only_module_docstrings() -> None:
    """
    Ensure non-callable summary docstrings remain acceptable.

    Parameters
    ----------
    None

    Returns
    -------
    None
        The test asserts that module-style summary docstrings are not flagged.
    """
    issues = validate_docstring(_validation_request("Module summary.", is_public=1))

    assert issues == []
