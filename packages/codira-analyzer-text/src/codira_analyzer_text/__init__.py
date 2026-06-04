"""Plain-text documentation analyzer for codira.

Responsibilities
----------------
- Claim only documentation-scoped plain-text files.
- Emit bounded deterministic documentation artifacts for accepted text files.
- Exclude fixtures, logs, generated outputs, and vendor material by policy.

Design principles
-----------------
The analyzer treats plain text as weaker structure than Markdown and only
indexes files whose path or filename clearly identifies repository
documentation.

Architectural role
------------------
This module belongs to the **document analyzer layer** for repository
documentation retrieval.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.models import AnalysisResult, DocumentationArtifact, ModuleArtifact
from codira.plugin_config import (
    AnalyzerPathFilters,
    analyzer_json_schema,
    analyzer_path_allowed,
    analyzer_path_filters_from_config,
    boolean_property,
    plugin_configuration_fingerprint,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

__all__ = ["TextAnalyzer", "build_analyzer"]

_DOCUMENTATION_PATH_PARTS = frozenset({"docs", "doc", "adr", "process"})
_DOCUMENTATION_FILE_STEMS = frozenset({"readme", "changelog", "license"})
_EXCLUDED_PATH_PARTS = frozenset(
    {
        ".artifacts",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "fixtures",
        "generated",
        "logs",
        "node_modules",
        "snapshots",
        "vendor",
        "vendors",
    }
)
_LOG_LIKE_SUFFIXES = (".log.txt", ".out.txt", ".err.txt")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_MAX_CHUNK_CHARS = 1800


def _sanitize_module_segment(segment: str) -> str:
    """
    Normalize one path segment for text document module naming.

    Parameters
    ----------
    segment : str
        Raw repository-relative path segment.

    Returns
    -------
    str
        Segment rewritten to avoid ambiguous dotted module names.
    """
    normalized = segment.strip().replace("-", "_").replace(".", "_")
    return normalized.lstrip("_") or "text"


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive a logical module name for one plain-text document.

    Parameters
    ----------
    path : pathlib.Path
        Text file being analyzed.
    root : pathlib.Path
        Repository root used for relative naming.

    Returns
    -------
    str
        Dotted document identity derived from the repository-relative path.
    """
    relative = path.relative_to(root)
    parent_segments = [
        _sanitize_module_segment(part) for part in relative.parent.parts if part
    ]
    filename_segment = _sanitize_module_segment(path.stem)
    return ".".join(("docs", *parent_segments, filename_segment))


def _module_stable_id(path: Path, root: Path) -> str:
    """
    Build the durable module identity for one plain-text document.

    Parameters
    ----------
    path : pathlib.Path
        Text file being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable text module identity.
    """
    return f"text:module:{path.relative_to(root).as_posix()}"


def _is_documentation_text_path(path: Path, root: Path) -> bool:
    """
    Return whether a text file is eligible for documentation indexing.

    Parameters
    ----------
    path : pathlib.Path
        Candidate text file.
    root : pathlib.Path
        Repository root used for relative policy checks.

    Returns
    -------
    bool
        ``True`` when the path is a documentation-scoped text file.
    """
    if path.suffix.lower() != ".txt":
        return False
    relative = path.relative_to(root)
    lowered_parts = tuple(part.lower() for part in relative.parts)
    if any(part in _EXCLUDED_PATH_PARTS for part in lowered_parts):
        return False
    lowered_name = relative.name.lower()
    if lowered_name.endswith(_LOG_LIKE_SUFFIXES):
        return False
    if relative.stem.lower() in _DOCUMENTATION_FILE_STEMS:
        return True
    return any(part in _DOCUMENTATION_PATH_PARTS for part in lowered_parts[:-1])


def _chunk_lines(text: str) -> tuple[tuple[int, int, str], ...]:
    """
    Split plain text into deterministic bounded documentation chunks.

    Parameters
    ----------
    text : str
        Raw text payload.

    Returns
    -------
    tuple[tuple[int, int, str], ...]
        One-based start line, end line, and normalized chunk text.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [part.strip() for part in _PARAGRAPH_SPLIT_RE.split(normalized)]
    chunks: list[tuple[int, int, str]] = []
    current: list[str] = []
    current_start_line = 1
    current_line = 1

    def flush(end_line: int) -> None:
        if not current:
            return
        chunks.append((current_start_line, end_line, "\n\n".join(current).strip()))
        current.clear()

    for paragraph in paragraphs:
        paragraph_line_count = paragraph.count("\n") + 1
        if not paragraph:
            current_line += 1
            continue
        candidate = "\n\n".join([*current, paragraph]).strip()
        if current and len(candidate) > _MAX_CHUNK_CHARS:
            flush(current_line - 1)
            current_start_line = current_line
        if not current:
            current_start_line = current_line
        current.append(paragraph)
        current_line += paragraph_line_count + 1

    flush(max(1, current_line - 2))
    return tuple(chunks)


def _documentation_artifacts(
    path: Path, root: Path
) -> tuple[DocumentationArtifact, ...]:
    """
    Build documentation artifacts for one accepted plain-text file.

    Parameters
    ----------
    path : pathlib.Path
        Text source file.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        File or bounded section artifacts for non-empty text.
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ()
    relative_path = path.relative_to(root).as_posix()
    chunks = _chunk_lines(text)
    if len(chunks) <= 1:
        end_lineno = text.count("\n") + 1
        return (
            DocumentationArtifact(
                stable_id=f"doc:file:{relative_path}:plain-text:1",
                kind="file",
                source_format="plain_text_document",
                source_path=path,
                lineno=1,
                end_lineno=end_lineno,
                title=path.stem,
                heading_path=(),
                text=text,
            ),
        )

    return tuple(
        DocumentationArtifact(
            stable_id=f"doc:section:{relative_path}:plain-text:{ordinal}",
            kind="section",
            source_format="plain_text_document",
            source_path=path,
            lineno=start_line,
            end_lineno=end_line,
            title=f"{path.stem} chunk {ordinal}",
            heading_path=(path.stem,),
            text=chunk_text,
        )
        for ordinal, (start_line, end_line, chunk_text) in enumerate(chunks, start=1)
    )


class TextAnalyzer:
    """
    Concrete plain-text analyzer for repository documentation indexing.

    Parameters
    ----------
    None

    Notes
    -----
    Text files emit documentation artifacts only. Eligibility is intentionally
    path-based so arbitrary prose and generated outputs stay out of the index.
    """

    name = "text"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.txt",)

    def __init__(self) -> None:
        self._path_filters = AnalyzerPathFilters()
        self._include_root_files = True
        self._include_docs_directories = True
        self._exclude_generated = True
        self._exclude_fixtures_logs = True
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the plain-text analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for text analyzer options.
        """

        return analyzer_json_schema(
            {
                "include_root_files": boolean_property(True),
                "include_docs_directories": boolean_property(True),
                "exclude_generated": boolean_property(True),
                "exclude_fixtures_logs": boolean_property(True),
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply plain-text analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.
        """

        self._path_filters = analyzer_path_filters_from_config(config)
        self._include_root_files = bool(config.get("include_root_files", True))
        self._include_docs_directories = bool(
            config.get("include_docs_directories", True)
        )
        self._exclude_generated = bool(config.get("exclude_generated", True))
        self._exclude_fixtures_logs = bool(config.get("exclude_fixtures_logs", True))
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return text analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from plain text documents to documentation
            artifacts.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_text:build_analyzer",
            supports=("documentation",),
            does_not_support=(
                "module",
                "type",
                "callable",
                "import",
                "constant",
                "variable",
                "namespace",
            ),
            mappings={
                "plain_text_document": "documentation",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a text path by suffix.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the path has a plain-text suffix.
        """
        return path.suffix.lower() == ".txt"

    def _is_configured_documentation_text_path(self, path: Path, root: Path) -> bool:
        """
        Return whether configured policy accepts one text path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate text file.
        root : pathlib.Path
            Repository root used for relative policy checks.

        Returns
        -------
        bool
            ``True`` when configured text policy accepts the file.
        """

        if path.suffix.lower() != ".txt":
            return False
        relative = path.relative_to(root)
        lowered_parts = tuple(part.lower() for part in relative.parts)
        generated_parts = {".artifacts", "build", "dist", "generated", "snapshots"}
        fixture_log_parts = {"fixtures", "logs"}
        other_excluded_parts = (
            _EXCLUDED_PATH_PARTS - generated_parts - fixture_log_parts
        )
        if any(part in other_excluded_parts for part in lowered_parts):
            return False
        if self._exclude_generated and any(
            part in generated_parts for part in lowered_parts
        ):
            return False
        if self._exclude_fixtures_logs and any(
            part in fixture_log_parts for part in lowered_parts
        ):
            return False
        if self._exclude_fixtures_logs and relative.name.lower().endswith(
            _LOG_LIKE_SUFFIXES
        ):
            return False
        if (
            self._include_root_files
            and len(relative.parts) == 1
            and relative.stem.lower() in _DOCUMENTATION_FILE_STEMS
        ):
            return True
        if self._include_docs_directories and any(
            part in _DOCUMENTATION_PATH_PARTS for part in lowered_parts[:-1]
        ):
            return True
        return False

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured filters allow a supported text path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the path is eligible and allowed by filters.
        """

        return self._is_configured_documentation_text_path(
            path,
            root,
        ) and analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one plain-text file into documentation artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Text source file.
        root : pathlib.Path
            Repository root used for relative identity derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Analysis result carrying documentation artifacts for eligible text
            files and no artifacts for excluded text files.
        """
        module = ModuleArtifact(
            name=_module_name_for_path(path, root),
            stable_id=_module_stable_id(path, root),
            docstring=None,
            has_docstring=0,
        )
        documentation: tuple[DocumentationArtifact, ...]
        if self._is_configured_documentation_text_path(path, root):
            documentation = _documentation_artifacts(path, root)
        else:
            documentation = ()
        return AnalysisResult(
            source_path=path,
            module=module,
            classes=(),
            functions=(),
            declarations=(),
            imports=(),
            documentation=documentation,
            index_symbols=False,
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party plain-text analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh text analyzer instance for registry discovery.
    """
    return TextAnalyzer()
