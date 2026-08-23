"""Docstring validation helpers used during indexing.

Responsibilities
----------------
- Inspect NumPy-style sections, detect malformed headings, and enumerate parameter documentation.
- Decide structured docstring requirements based on callable metadata such as returns, yields, and raises.
- Validate docstrings and emit diagnostics consumed by the indexer and CLI.

Design principles
-----------------
Validation helpers focus on deterministic parsing of cleaned docstrings and avoid heuristics that depend on runtime state.

Architectural role
------------------
This module belongs to the **docstring infrastructure layer** that enforces NumPy-style rules across analyzer outputs.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING

from codira.contracts import (
    DocumentationAuditDiagnostic,
    DocumentationAuditRequest,
    DocumentationAuditResult,
    DocumentationAuditSeverity,
)

if TYPE_CHECKING:
    from pathlib import Path

    from codira.config import DocumentationAuditRouteConfig

REQUIRED_SECTIONS = [
    "Parameters",
    "Returns",
    "Yields",
]

OPTIONAL_SECTIONS = [
    "Raises",
    "Notes",
    "Examples",
]
KNOWN_SECTIONS = REQUIRED_SECTIONS + OPTIONAL_SECTIONS
SECTION_HEADING_RE = re.compile(r"^[A-Z][A-Za-z ]+$")
PARAMETER_LINE_RE = re.compile(r"^([*]{0,2}[A-Za-z_][A-Za-z0-9_]*)\s*:")
GOOGLE_ARGS_RE = re.compile(r"^\s*(Args|Arguments):\s*$")
GOOGLE_RETURNS_RE = re.compile(r"^\s*Returns:\s*$")
GOOGLE_RAISES_RE = re.compile(r"^\s*Raises:\s*$")
JSDOC_PARAM_RE = re.compile(
    r"^\s*@param\s+(?:\{[^}]*\}\s*)?"
    r"(?P<name>\[[^\]]+\]|[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
JSDOC_RETURN_RE = re.compile(r"^\s*@returns?\b")
JSDOC_THROWS_RE = re.compile(r"^\s*@throws?\b")
TSDOC_PARAM_RE = re.compile(r"^\s*@param\s+(?P<name>[A-Za-z_$][\w$]*)\b", re.MULTILINE)


def _documentation_audit_config_schema() -> dict[str, object]:
    """
    Return the common documentation audit plugin configuration schema.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Strict JSON Schema accepted by first-party documentation audit plugins.
    """

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "enabled": {"type": "boolean"},
        },
    }


@dataclass(frozen=True)
class DocstringValidationRequest:
    """
    Request parameters for docstring validation.

    Parameters
    ----------
    doc : str | None
        Docstring text to validate.
    is_public : int
        Public visibility flag, where ``1`` means public and ``0`` means
        private.
    parameters : list[str]
        Logical parameter names declared by the callable.
    require_callable_sections : bool
        Whether callable-specific sections must be present.
    yields_value : bool
        Whether the callable yields values.
    returns_value : bool
        Whether the callable returns values.
    raises_exception : bool
        Whether the callable raises exceptions.
    """

    doc: str | None
    is_public: int
    parameters: list[str]
    require_callable_sections: bool = False
    yields_value: bool = False
    returns_value: bool = False
    raises_exception: bool = False


@dataclass(frozen=True)
class DocumentationAuditIssue:
    """
    Persistable documentation audit issue with provenance metadata.

    Parameters
    ----------
    issue_type : str
        Legacy audit issue type exposed to existing query consumers.
    message : str
        User-facing labeled diagnostic message.
    audit_language : str
        Analyzer language selected by the route.
    audit_plugin_name : str
        Documentation audit plugin that produced the diagnostic.
    audit_plugin_version : str
        Plugin implementation version.
    convention_name : str
        Documentation convention evaluated by the plugin.
    convention_version : str
        Convention profile version.
    rule_id : str
        Stable plugin rule identifier.
    severity : {"info", "warning", "error"}
        Diagnostic severity.
    """

    issue_type: str
    message: str
    audit_language: str
    audit_plugin_name: str
    audit_plugin_version: str
    convention_name: str
    convention_version: str
    rule_id: str
    severity: DocumentationAuditSeverity


def _iter_lines(doc: str) -> list[str]:
    """
    Split a docstring into normalized lines.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    list[str]
        Normalized docstring lines.
    """
    return [line.rstrip() for line in inspect.cleandoc(doc).splitlines()]


def _section_map(doc: str) -> dict[str, tuple[int, int]]:
    """
    Locate NumPy-style section bodies in a docstring.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    dict[str, tuple[int, int]]
        Mapping from section name to inclusive start and exclusive end line
        indices for that section body.
    """
    lines = _iter_lines(doc)
    sections: dict[str, tuple[int, int]] = {}
    headers: list[tuple[str, int]] = []

    for index, line in enumerate(lines[:-1]):
        if line not in KNOWN_SECTIONS:
            continue
        underline = lines[index + 1].strip()
        if underline and set(underline) == {"-"} and len(underline) >= len(line):
            headers.append((line, index))

    for header_index, (name, start) in enumerate(headers):
        body_start = start + 2
        body_end = len(lines)
        if header_index + 1 < len(headers):
            body_end = headers[header_index + 1][1]
        sections[name] = (body_start, body_end)

    return sections


def _malformed_sections(doc: str) -> list[str]:
    """
    Detect known section headings that are not in NumPy format.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    list[str]
        Known section names that appear without a valid underline.
    """
    lines = _iter_lines(doc)
    valid = set(_section_map(doc))
    malformed: list[str] = []

    for index, line in enumerate(lines):
        if line not in KNOWN_SECTIONS or line in valid:
            continue
        if not SECTION_HEADING_RE.match(line):
            continue
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if not next_line or set(next_line) != {"-"}:
            malformed.append(line)

    return malformed


def _parameter_section_names(doc: str) -> set[str]:
    """
    Extract documented parameter names from the ``Parameters`` section.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    set[str]
        Parameter names documented in the ``Parameters`` section.
    """
    sections = _section_map(doc)
    if "Parameters" not in sections:
        return set()

    lines = _iter_lines(doc)
    start, end = sections["Parameters"]
    names: set[str] = set()

    for line in lines[start:end]:
        match = PARAMETER_LINE_RE.match(line.strip())
        if match is None:
            continue
        names.add(match.group(1).lstrip("*"))

    return names


def _requires_structured_docstring(
    *,
    require_callable_sections: bool,
    raises_exception: bool,
) -> bool:
    """
    Decide whether a docstring must use structured NumPy sections.

    Parameters
    ----------
    require_callable_sections : bool
        Whether the audited object is a callable governed by the strict
        project profile.
    raises_exception : bool
        Whether the callable explicitly raises.

    Returns
    -------
    bool
        ``True`` when structured sections are required.
    """
    return require_callable_sections or raises_exception


def is_numpy_style(doc: str) -> bool:
    """
    Check whether a docstring contains basic NumPy-style sections.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    bool
        ``True`` when the docstring contains at least one core NumPy section.
    """
    sections = _section_map(doc)
    return "Parameters" in sections or "Returns" in sections or "Yields" in sections


def find_missing_sections(
    doc: str,
    *,
    require_parameters_section: bool = False,
    require_returns_section: bool = False,
    require_yields_section: bool = False,
    raises_exception: bool = False,
) -> list[str]:
    """
    List required or conditional NumPy sections missing from a docstring.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.
    require_parameters_section : bool, optional
        Whether the ``Parameters`` section is required.
    require_returns_section : bool, optional
        Whether the ``Returns`` section is required.
    require_yields_section : bool, optional
        Whether the ``Yields`` section is required.
    raises_exception : bool, optional
        Whether the callable explicitly raises an exception.

    Returns
    -------
    list[str]
        Missing section names implied by the supplied callable metadata.
    """
    sections = _section_map(doc)
    missing: list[str] = []

    if require_parameters_section and "Parameters" not in sections:
        missing.append("Parameters")

    if require_returns_section and "Returns" not in sections:
        missing.append("Returns")

    if require_yields_section and "Yields" not in sections:
        missing.append("Yields")

    if raises_exception and "Raises" not in sections:
        missing.append("Raises")

    return missing


def find_unexpected_sections(
    doc: str,
    *,
    allow_returns_section: bool = False,
    allow_yields_section: bool = False,
) -> list[str]:
    """
    List NumPy sections that are present but semantically unsupported.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.
    allow_returns_section : bool, optional
        Whether the ``Returns`` section is semantically valid for the audited
        callable.
    allow_yields_section : bool, optional
        Whether the ``Yields`` section is semantically valid for the audited
        callable.

    Returns
    -------
    list[str]
        Unexpected section names present in the docstring.
    """
    sections = _section_map(doc)
    unexpected: list[str] = []

    if "Returns" in sections and not allow_returns_section:
        unexpected.append("Returns")

    if "Yields" in sections and not allow_yields_section:
        unexpected.append("Yields")

    return unexpected


def has_raises_section(doc: str) -> bool:
    """
    Check whether a docstring declares a ``Raises`` section.

    Parameters
    ----------
    doc : str
        Docstring text to inspect.

    Returns
    -------
    bool
        ``True`` when the docstring contains a ``Raises`` heading.
    """
    return "Raises" in _section_map(doc)


def validate_docstring(
    request: DocstringValidationRequest,
) -> list[tuple[str, str]]:
    """
    Validate a docstring against the project's minimal style rules.

    Parameters
    ----------
    request : DocstringValidationRequest
        Docstring validation request carrying visibility and callable metadata.

    Returns
    -------
    list[tuple[str, str]]
        Validation issues as ``(issue_type, message)`` tuples.
    """
    issues: list[tuple[str, str]] = []

    if not request.doc:
        if not request.is_public:
            return []
        return [("missing", "Missing docstring")]

    sections = _section_map(request.doc)

    if not is_numpy_style(request.doc) and _requires_structured_docstring(
        require_callable_sections=request.require_callable_sections,
        raises_exception=request.raises_exception,
    ):
        issues.append(("non_numpy", "Docstring not in NumPy style"))

    for section in _malformed_sections(request.doc):
        issues.append(
            ("malformed_section", f"Malformed NumPy section heading: {section}")
        )

    for section in find_missing_sections(
        request.doc,
        require_parameters_section=request.require_callable_sections,
        require_returns_section=(
            request.require_callable_sections and not request.yields_value
        ),
        require_yields_section=(
            request.require_callable_sections and request.yields_value
        ),
        raises_exception=request.raises_exception,
    ):
        issues.append(("missing_section", f"Missing section: {section}"))

    for section in find_unexpected_sections(
        request.doc,
        allow_returns_section=(not request.yields_value) or request.returns_value,
        allow_yields_section=request.yields_value,
    ):
        issues.append(("unexpected_section", f"Unexpected section: {section}"))

    documented_parameters = _parameter_section_names(request.doc)
    for parameter in request.parameters:
        if "Parameters" not in sections:
            break
        if parameter not in documented_parameters:
            issues.append(
                (
                    "missing_parameter",
                    f"Parameter not documented: {parameter}",
                )
            )

    return issues


class NumpyDocumentationAuditPlugin:
    """
    Documentation audit plugin for NumPy-style Python docstrings.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless.
    """

    name = "numpy"
    version = "1"
    languages = ("python",)
    conventions = ("numpy",)

    def configuration_json_schema(self) -> dict[str, object]:
        """
        Return the strict plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            JSON Schema accepted by the plugin config table.
        """

        return _documentation_audit_config_schema()

    def audit_documentation(
        self,
        request: DocumentationAuditRequest,
    ) -> DocumentationAuditResult:
        """
        Validate one artifact with the NumPy docstring profile.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Documentation artifact to validate.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Structured diagnostics emitted for the artifact.
        """

        diagnostics = [
            DocumentationAuditDiagnostic(
                code=issue_type,
                message=message,
                severity="warning",
                plugin_name=self.name,
                plugin_version=self.version,
                convention=request.convention,
            )
            for issue_type, message in validate_docstring(
                DocstringValidationRequest(
                    doc=request.doc,
                    is_public=1,
                    parameters=list(request.parameters),
                    require_callable_sections=request.require_callable_sections,
                    yields_value=request.yields_value,
                    returns_value=request.returns_value,
                    raises_exception=request.raises_exception,
                )
            )
        ]
        return DocumentationAuditResult(diagnostics=diagnostics)


class GooglePythonDocumentationAuditPlugin:
    """
    Documentation audit plugin for Google-style Python docstrings.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless.
    """

    name = "google"
    version = "1"
    languages = ("python",)
    conventions = ("google",)

    def configuration_json_schema(self) -> dict[str, object]:
        """
        Return the strict plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            JSON Schema accepted by the plugin config table.
        """

        return _documentation_audit_config_schema()

    def audit_documentation(
        self,
        request: DocumentationAuditRequest,
    ) -> DocumentationAuditResult:
        """
        Validate one artifact with a bounded Google-style profile.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Documentation artifact to validate.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Structured diagnostics emitted for the artifact.
        """

        diagnostics: list[DocumentationAuditDiagnostic] = []
        if not request.doc:
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing",
                    message="Missing docstring",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
            return DocumentationAuditResult(diagnostics=diagnostics)

        text = inspect.cleandoc(request.doc)
        if request.parameters and GOOGLE_ARGS_RE.search(text) is None:
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_section",
                    message="Missing section: Args",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        if (
            request.require_callable_sections
            and request.returns_value
            and GOOGLE_RETURNS_RE.search(text) is None
        ):
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_section",
                    message="Missing section: Returns",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        if request.raises_exception and GOOGLE_RAISES_RE.search(text) is None:
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_section",
                    message="Missing section: Raises",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        return DocumentationAuditResult(diagnostics=diagnostics)


class DoxygenDocumentationAuditPlugin:
    """
    Documentation audit plugin for bounded Doxygen checks on C-family files.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless.
    """

    name = "doxygen"
    version = "1"
    languages = ("c", "cpp")
    conventions = ("doxygen",)

    def configuration_json_schema(self) -> dict[str, object]:
        """
        Return the strict plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            JSON Schema accepted by the plugin config table.
        """

        return _documentation_audit_config_schema()

    def audit_documentation(
        self,
        request: DocumentationAuditRequest,
    ) -> DocumentationAuditResult:
        """
        Validate one C-family artifact with a bounded Doxygen profile.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Documentation artifact to validate.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Structured diagnostics emitted for the artifact.
        """

        if request.doc and ("/**" in request.doc or "///" in request.doc):
            return DocumentationAuditResult(diagnostics=())
        return DocumentationAuditResult(
            diagnostics=(
                DocumentationAuditDiagnostic(
                    code="missing_doxygen",
                    message="Missing Doxygen documentation",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                ),
            )
        )


class JSDocDocumentationAuditPlugin:
    """Audit explicit JSDoc fields on JavaScript documentation artifacts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless and inspect only analyzer-emitted text.
    """

    name = "jsdoc"
    version = "1"
    languages = ("javascript",)
    conventions = ("jsdoc",)

    def configuration_json_schema(self) -> dict[str, object]:
        """Return the strict common audit-plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            Schema accepting only the shared enabled property.
        """
        return _documentation_audit_config_schema()

    def audit_documentation(
        self, request: DocumentationAuditRequest
    ) -> DocumentationAuditResult:
        """Validate one analyzer-emitted JavaScript documentation artifact.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Routed JSDoc artifact and callable metadata.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Deterministic missing, empty, and tag-completeness diagnostics.
        """
        if request.doc is None:
            return DocumentationAuditResult(
                diagnostics=(
                    DocumentationAuditDiagnostic(
                        code="missing_jsdoc",
                        message="Missing JSDoc documentation",
                        severity="warning",
                        plugin_name=self.name,
                        plugin_version=self.version,
                        convention=request.convention,
                    ),
                )
            )
        text = inspect.cleandoc(request.doc)
        if not text:
            return DocumentationAuditResult(
                diagnostics=(
                    DocumentationAuditDiagnostic(
                        code="empty_jsdoc",
                        message="JSDoc documentation is empty",
                        severity="warning",
                        plugin_name=self.name,
                        plugin_version=self.version,
                        convention=request.convention,
                    ),
                )
            )
        documented_parameters = {
            match.group("name").strip("[]").split("=", maxsplit=1)[0]
            for match in JSDOC_PARAM_RE.finditer(text)
        }
        diagnostics: list[DocumentationAuditDiagnostic] = []
        for parameter in request.parameters:
            if parameter not in documented_parameters:
                diagnostics.append(
                    DocumentationAuditDiagnostic(
                        code="missing_jsdoc_param",
                        message=f"Parameter not documented: {parameter}",
                        severity="warning",
                        plugin_name=self.name,
                        plugin_version=self.version,
                        convention=request.convention,
                    )
                )
        if (
            request.require_callable_sections
            and request.returns_value
            and JSDOC_RETURN_RE.search(text) is None
        ):
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_jsdoc_returns",
                    message="Missing JSDoc tag: @returns",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        if request.raises_exception and JSDOC_THROWS_RE.search(text) is None:
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_jsdoc_throws",
                    message="Missing JSDoc tag: @throws",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        return DocumentationAuditResult(diagnostics=diagnostics)


class TSDocDocumentationAuditPlugin:
    """Audit explicit TSDoc fields emitted by the TypeScript analyzer.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless and validate explicit documentation only.
    """

    name = "tsdoc"
    version = "1"
    languages = ("typescript",)
    conventions = ("tsdoc",)

    def configuration_json_schema(self) -> dict[str, object]:
        """Return the strict common audit-plugin configuration schema.

        Returns
        -------
        dict[str, object]
            Schema accepting only the shared enabled property.
        """
        return _documentation_audit_config_schema()

    def audit_documentation(
        self, request: DocumentationAuditRequest
    ) -> DocumentationAuditResult:
        """Validate one analyzer-emitted TypeScript documentation artifact.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Routed TSDoc artifact and callable metadata.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Stable diagnostics for missing or incomplete TSDoc fields.
        """
        if request.doc is None:
            return DocumentationAuditResult(
                diagnostics=(
                    DocumentationAuditDiagnostic(
                        code="missing_tsdoc",
                        message="Missing TSDoc documentation",
                        severity="warning",
                        plugin_name=self.name,
                        plugin_version=self.version,
                        convention=request.convention,
                    ),
                )
            )
        text = inspect.cleandoc(request.doc)
        if not text:
            return DocumentationAuditResult(
                diagnostics=(
                    DocumentationAuditDiagnostic(
                        code="empty_tsdoc",
                        message="TSDoc documentation is empty",
                        severity="warning",
                        plugin_name=self.name,
                        plugin_version=self.version,
                        convention=request.convention,
                    ),
                )
            )
        documented = {match.group("name") for match in TSDOC_PARAM_RE.finditer(text)}
        diagnostics = [
            DocumentationAuditDiagnostic(
                code="missing_tsdoc_param",
                message=f"Parameter not documented: {parameter}",
                severity="warning",
                plugin_name=self.name,
                plugin_version=self.version,
                convention=request.convention,
            )
            for parameter in request.parameters
            if parameter not in documented
        ]
        if (
            request.require_callable_sections
            and request.returns_value
            and JSDOC_RETURN_RE.search(text) is None
        ):
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_tsdoc_returns",
                    message="Missing TSDoc tag: @returns",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        if request.raises_exception and JSDOC_THROWS_RE.search(text) is None:
            diagnostics.append(
                DocumentationAuditDiagnostic(
                    code="missing_tsdoc_throws",
                    message="Missing TSDoc tag: @throws",
                    severity="warning",
                    plugin_name=self.name,
                    plugin_version=self.version,
                    convention=request.convention,
                )
            )
        return DocumentationAuditResult(diagnostics=diagnostics)


class RustdocDocumentationAuditPlugin:
    """Documentation audit plugin for native Rustdoc artifacts.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Instances are stateless.
    """

    name = "rustdoc"
    version = "1"
    languages = ("rust",)
    conventions = ("rustdoc",)

    def configuration_json_schema(self) -> dict[str, object]:
        """Return the strict plugin configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        dict[str, object]
            JSON Schema accepted by the plugin config table.
        """
        return _documentation_audit_config_schema()

    def audit_documentation(
        self, request: DocumentationAuditRequest
    ) -> DocumentationAuditResult:
        """Validate one attached Rustdoc artifact.

        Parameters
        ----------
        request : codira.contracts.DocumentationAuditRequest
            Rust artifact selected by the configured audit route.

        Returns
        -------
        codira.contracts.DocumentationAuditResult
            Missing-documentation or empty-documentation diagnostics.
        """
        if request.doc is None:
            diagnostic = DocumentationAuditDiagnostic(
                code="missing_rustdoc",
                message="Missing Rustdoc documentation",
                severity="warning",
                plugin_name=self.name,
                plugin_version=self.version,
                convention=request.convention,
            )
            return DocumentationAuditResult(diagnostics=(diagnostic,))
        if request.doc.strip():
            return DocumentationAuditResult(diagnostics=())
        diagnostic = DocumentationAuditDiagnostic(
            code="empty_rustdoc",
            message="Rustdoc documentation is empty",
            severity="warning",
            plugin_name=self.name,
            plugin_version=self.version,
            convention=request.convention,
        )
        return DocumentationAuditResult(diagnostics=(diagnostic,))


def _language_for_path(source_path: Path) -> str:
    """
    Infer the analyzer language for a source path.

    Parameters
    ----------
    source_path : pathlib.Path
        Source path to classify.

    Returns
    -------
    str
        Analyzer language label used by documentation audit routing.
    """

    suffix = source_path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".c", ".h"}:
        return "c"
    if suffix in {".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ipp"}:
        return "cpp"
    if suffix == ".rs":
        return "rust"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix in {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    return suffix.lstrip(".")


def _matches_route_path(
    *,
    relative_path: str,
    include_paths: tuple[str, ...],
    exclude_paths: tuple[str, ...],
) -> bool:
    """
    Return whether a route accepts a repo-relative path.

    Parameters
    ----------
    relative_path : str
        POSIX-style repo-relative source path.
    include_paths : tuple[str, ...]
        Include glob patterns. Empty includes every path.
    exclude_paths : tuple[str, ...]
        Exclude glob patterns.

    Returns
    -------
    bool
        ``True`` when the path is included and not excluded.
    """

    included = not include_paths or any(
        fnmatch(relative_path, pattern) for pattern in include_paths
    )
    excluded = any(fnmatch(relative_path, pattern) for pattern in exclude_paths)
    return included and not excluded


def _relative_route_path(*, root: Path, source_path: Path) -> str:
    """
    Return the POSIX route path for one source file.

    Parameters
    ----------
    root : pathlib.Path
        Repository root.
    source_path : pathlib.Path
        Source path to normalize.

    Returns
    -------
    str
        POSIX-style repo-relative path when possible.
    """

    if not source_path.is_absolute():
        return source_path.as_posix()
    try:
        return source_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return source_path.as_posix()


def _matching_documentation_audit_routes(
    *,
    root: Path,
    source_path: Path,
) -> tuple[str, list[DocumentationAuditRouteConfig]]:
    """
    Return matching documentation audit routes for one source path.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective config selects routes.
    source_path : pathlib.Path
        Source file path.

    Returns
    -------
    tuple[str, list[codira.config.DocumentationAuditRouteConfig]]
        Inferred language and matching route objects.
    """

    from codira.config import load_effective_config  # noqa: PLC0415

    config = load_effective_config(root=root)
    language = _language_for_path(source_path)
    relative_path = _relative_route_path(root=root, source_path=source_path)
    matches = [
        route
        for route in config.plugins.documentation_audit_routes
        if route.language == language
        and _matches_route_path(
            relative_path=relative_path,
            include_paths=route.include_paths,
            exclude_paths=route.exclude_paths,
        )
    ]
    return language, matches


def documentation_audit_route_metadata(
    *,
    root: Path,
    source_path: Path,
) -> dict[str, str] | None:
    """
    Return JSON-ready route metadata for one audited source path.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective config selects routes.
    source_path : pathlib.Path
        Source file path.

    Returns
    -------
    dict[str, str] | None
        Route metadata with language, convention, and plugin, or ``None`` when
        no single route matches.
    """

    language, matches = _matching_documentation_audit_routes(
        root=root,
        source_path=source_path,
    )
    if len(matches) != 1:
        return None
    route = matches[0]
    return {
        "language": language,
        "convention": route.convention,
        "plugin": route.plugin,
    }


def validate_documentation_issues_with_configured_plugin(  # noqa: PLR0913
    *,
    root: Path,
    source_path: Path,
    stable_id: str,
    symbol_name: str,
    artifact_kind: str,
    label: str,
    doc: str | None,
    is_public: int,
    parameters: list[str] | None = None,
    require_callable_sections: bool = False,
    yields_value: bool = False,
    returns_value: bool = False,
    raises_exception: bool = False,
) -> list[DocumentationAuditIssue]:
    """
    Validate one artifact through explicit documentation-audit routing.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective config selects routes.
    source_path : pathlib.Path
        Source file owning the artifact.
    stable_id : str
        Stable analyzer-owned artifact identifier.
    symbol_name : str
        Artifact name shown in diagnostics.
    artifact_kind : str
        Artifact kind shown to plugins.
    label : str
        Existing user-facing label prefixed onto issue messages.
    doc : str | None
        Documentation text to validate.
    is_public : int
        Public visibility flag. Private artifacts are skipped.
    parameters : list[str] | None, optional
        Callable parameters.
    require_callable_sections : bool, optional
        Whether callable sections are required.
    yields_value : bool, optional
        Whether the callable yields values.
    returns_value : bool, optional
        Whether the callable returns values.
    raises_exception : bool, optional
        Whether the callable raises exceptions.

    Returns
    -------
    list[DocumentationAuditIssue]
        Persistable issue records with plugin and convention provenance.
    """

    if not is_public:
        return []

    from codira.registry import documentation_audit_plugins  # noqa: PLC0415

    language, matches = _matching_documentation_audit_routes(
        root=root,
        source_path=source_path,
    )
    if not matches:
        return []
    if len(matches) > 1:
        relative_path = _relative_route_path(root=root, source_path=source_path)
        return [
            DocumentationAuditIssue(
                issue_type="ambiguous_route",
                message=(
                    f"{label}: Ambiguous documentation audit routes for {relative_path}"
                ),
                audit_language=language,
                audit_plugin_name="",
                audit_plugin_version="",
                convention_name="",
                convention_version="",
                rule_id="ambiguous_route",
                severity="error",
            )
        ]

    route = matches[0]
    plugins = documentation_audit_plugins(root=root)
    plugin = plugins.get(route.plugin)
    if plugin is None:
        return [
            DocumentationAuditIssue(
                issue_type="unsupported_plugin",
                message=(
                    f"{label}: Unsupported documentation audit plugin: {route.plugin}"
                ),
                audit_language=language,
                audit_plugin_name=route.plugin,
                audit_plugin_version="",
                convention_name=route.convention,
                convention_version="",
                rule_id="unsupported_plugin",
                severity="error",
            )
        ]
    if language not in plugin.languages or route.convention not in plugin.conventions:
        return [
            DocumentationAuditIssue(
                issue_type="unsupported_route",
                message=(
                    f"{label}: Documentation audit plugin {route.plugin} does not "
                    f"support {language}/{route.convention}"
                ),
                audit_language=language,
                audit_plugin_name=plugin.name,
                audit_plugin_version=plugin.version,
                convention_name=route.convention,
                convention_version="",
                rule_id="unsupported_route",
                severity="error",
            )
        ]

    result = plugin.audit_documentation(
        DocumentationAuditRequest(
            source_path=source_path,
            language=language,
            convention=route.convention,
            artifact_kind=artifact_kind,
            symbol_name=symbol_name,
            stable_id=stable_id,
            doc=doc,
            parameters=tuple(parameters or ()),
            require_callable_sections=require_callable_sections,
            yields_value=yields_value,
            returns_value=returns_value,
            raises_exception=raises_exception,
        )
    )
    return [
        DocumentationAuditIssue(
            issue_type=diagnostic.code,
            message=f"{label}: {diagnostic.message}",
            audit_language=language,
            audit_plugin_name=diagnostic.plugin_name,
            audit_plugin_version=diagnostic.plugin_version,
            convention_name=diagnostic.convention,
            convention_version=diagnostic.convention_version,
            rule_id=diagnostic.code,
            severity=diagnostic.severity,
        )
        for diagnostic in result.diagnostics
    ]


def validate_documentation_with_configured_plugin(  # noqa: PLR0913
    *,
    root: Path,
    source_path: Path,
    stable_id: str,
    symbol_name: str,
    artifact_kind: str,
    label: str,
    doc: str | None,
    is_public: int,
    parameters: list[str] | None = None,
    require_callable_sections: bool = False,
    yields_value: bool = False,
    returns_value: bool = False,
    raises_exception: bool = False,
) -> list[tuple[str, str]]:
    """
    Validate one artifact and return legacy issue tuples.

    Parameters
    ----------
    root : pathlib.Path
        Repository root whose effective config selects routes.
    source_path : pathlib.Path
        Source file owning the artifact.
    stable_id : str
        Stable analyzer-owned artifact identifier.
    symbol_name : str
        Artifact name shown in diagnostics.
    artifact_kind : str
        Artifact kind shown to plugins.
    label : str
        Existing user-facing label prefixed onto issue messages.
    doc : str | None
        Documentation text to validate.
    is_public : int
        Public visibility flag. Private artifacts are skipped.
    parameters : list[str] | None, optional
        Callable parameters.
    require_callable_sections : bool, optional
        Whether callable sections are required.
    yields_value : bool, optional
        Whether the callable yields values.
    returns_value : bool, optional
        Whether the callable returns values.
    raises_exception : bool, optional
        Whether the callable raises exceptions.

    Returns
    -------
    list[tuple[str, str]]
        Issue code and labeled message pairs.
    """

    return [
        (issue.issue_type, issue.message)
        for issue in validate_documentation_issues_with_configured_plugin(
            root=root,
            source_path=source_path,
            stable_id=stable_id,
            symbol_name=symbol_name,
            artifact_kind=artifact_kind,
            label=label,
            doc=doc,
            is_public=is_public,
            parameters=parameters,
            require_callable_sections=require_callable_sections,
            yields_value=yields_value,
            returns_value=returns_value,
            raises_exception=raises_exception,
        )
    ]
