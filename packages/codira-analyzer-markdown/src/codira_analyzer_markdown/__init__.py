"""Markdown documentation analyzer for codira.

Responsibilities
----------------
- Claim Markdown documents through the analyzer plugin contract.
- Emit deterministic heading-section documentation artifacts.
- Keep Markdown parsing lightweight and independent from query-layer ranking.

Design principles
-----------------
The analyzer indexes documents, not arbitrary prose, and keeps section
identity stable through path, heading hierarchy, and deterministic ordinals.

Architectural role
------------------
This module belongs to the **document analyzer layer** for repository
documentation retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from codira.contracts import AnalyzerCapabilityDeclaration
from codira.models import (
    AnalysisResult,
    DocumentationArtifact,
    ModuleArtifact,
)
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

__all__ = ["MarkdownAnalyzer", "build_analyzer"]

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _Heading:
    """
    Parsed Markdown heading metadata.

    Parameters
    ----------
    level : int
        Markdown heading level from one to six.
    title : str
        Heading text without leading hash markers.
    lineno : int
        One-based source line number for the heading.
    index : int
        Zero-based line index for the heading.
    path : tuple[str, ...]
        Heading hierarchy active at this heading.
    ordinal : int
        Deterministic ordinal for duplicate heading paths in one file.
    """

    level: int
    title: str
    lineno: int
    index: int
    path: tuple[str, ...]
    ordinal: int


def _sanitize_module_segment(segment: str) -> str:
    """
    Normalize one path segment for Markdown module naming.

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
    return normalized.lstrip("_") or "markdown"


def _module_name_for_path(path: Path, root: Path) -> str:
    """
    Derive a logical module name for one Markdown document.

    Parameters
    ----------
    path : pathlib.Path
        Markdown file being analyzed.
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
    Build the durable module identity for one Markdown document.

    Parameters
    ----------
    path : pathlib.Path
        Markdown file being analyzed.
    root : pathlib.Path
        Repository root used for relative identity derivation.

    Returns
    -------
    str
        Durable Markdown module identity.
    """
    return f"markdown:module:{path.relative_to(root).as_posix()}"


def _strip_front_matter(lines: list[str]) -> tuple[list[str], int]:
    """
    Remove leading YAML front matter from Markdown source lines.

    Parameters
    ----------
    lines : list[str]
        Original Markdown source lines.

    Returns
    -------
    tuple[list[str], int]
        Remaining lines and the one-based line offset for the first remaining
        line.
    """
    if not lines or lines[0].strip() != "---":
        return lines, 1
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[index + 1 :], index + 2
    return lines, 1


def _slug_heading_path(path: tuple[str, ...]) -> str:
    """
    Render one heading path as a deterministic lowercase slug.

    Parameters
    ----------
    path : tuple[str, ...]
        Heading hierarchy to render.

    Returns
    -------
    str
        Slash-separated slug path for stable documentation identities.
    """
    slugs: list[str] = []
    for title in path:
        slug = _SLUG_RE.sub("-", title.lower()).strip("-")
        slugs.append(slug or "section")
    return "/".join(slugs) or "file"


def _markdown_headings(lines: list[str], *, line_offset: int) -> tuple[_Heading, ...]:
    """
    Parse Markdown headings outside fenced code blocks.

    Parameters
    ----------
    lines : list[str]
        Markdown source lines after front matter removal.
    line_offset : int
        One-based original line number for ``lines[0]``.

    Returns
    -------
    tuple[_Heading, ...]
        Parsed headings in source order with duplicate-path ordinals.
    """
    headings: list[_Heading] = []
    heading_stack: list[tuple[int, str]] = []
    path_counts: dict[tuple[str, ...], int] = {}
    in_fence = False

    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group(1))
        title = match.group(2).strip()
        heading_stack = [
            (stack_level, stack_title)
            for stack_level, stack_title in heading_stack
            if stack_level < level
        ]
        heading_stack.append((level, title))
        path = tuple(stack_title for _stack_level, stack_title in heading_stack)
        path_counts[path] = path_counts.get(path, 0) + 1
        headings.append(
            _Heading(
                level=level,
                title=title,
                lineno=line_offset + index,
                index=index,
                path=path,
                ordinal=path_counts[path],
            )
        )
    return tuple(headings)


def _section_text(lines: list[str], start_index: int, end_index: int) -> str:
    """
    Normalize one Markdown section payload.

    Parameters
    ----------
    lines : list[str]
        Markdown source lines after front matter removal.
    start_index : int
        Inclusive zero-based section start index.
    end_index : int
        Exclusive zero-based section end index.

    Returns
    -------
    str
        Section text with leading and trailing blank lines removed.
    """
    return "\n".join(lines[start_index:end_index]).strip()


def _documentation_artifacts(
    path: Path,
    root: Path,
    *,
    strip_front_matter: bool = True,
    emit_file_artifact_without_headings: bool = True,
    min_heading_level: int = 1,
    max_heading_level: int = 6,
) -> tuple[DocumentationArtifact, ...]:
    """
    Build documentation artifacts for one Markdown file.

    Parameters
    ----------
    path : pathlib.Path
        Markdown source file.
    root : pathlib.Path
        Repository root used for relative identity derivation.
    strip_front_matter : bool, optional
        Whether YAML front matter should be removed before section extraction.
    emit_file_artifact_without_headings : bool, optional
        Whether heading-less Markdown files should emit a file artifact.
    min_heading_level : int, optional
        Lowest accepted Markdown heading level.
    max_heading_level : int, optional
        Highest accepted Markdown heading level.

    Returns
    -------
    tuple[codira.models.DocumentationArtifact, ...]
        Heading-section artifacts, or one file-level artifact when the file has
        no headings but contains non-empty text.
    """
    original_lines = path.read_text(encoding="utf-8").splitlines()
    if strip_front_matter:
        lines, line_offset = _strip_front_matter(original_lines)
    else:
        lines, line_offset = original_lines, 1
    headings = tuple(
        heading
        for heading in _markdown_headings(lines, line_offset=line_offset)
        if min_heading_level <= heading.level <= max_heading_level
    )
    relative_path = path.relative_to(root).as_posix()

    if not headings:
        if not emit_file_artifact_without_headings:
            return ()
        text = "\n".join(lines).strip()
        if not text:
            return ()
        return (
            DocumentationArtifact(
                stable_id=f"doc:file:{relative_path}:file:1",
                kind="file",
                source_format="markdown_section",
                source_path=path,
                lineno=line_offset,
                end_lineno=line_offset + len(lines) - 1,
                title=path.stem,
                heading_path=(),
                text=text,
            ),
        )

    artifacts: list[DocumentationArtifact] = []
    for index, heading in enumerate(headings):
        end_index = (
            headings[index + 1].index if index + 1 < len(headings) else len(lines)
        )
        text = _section_text(lines, heading.index, end_index)
        if not text:
            continue
        stable_heading_path = _slug_heading_path(heading.path)
        artifacts.append(
            DocumentationArtifact(
                stable_id=(
                    f"doc:section:{relative_path}:{stable_heading_path}:"
                    f"{heading.ordinal}"
                ),
                kind="section",
                source_format="markdown_section",
                source_path=path,
                lineno=heading.lineno,
                end_lineno=line_offset + end_index - 1,
                title=heading.title,
                heading_path=heading.path,
                text=text,
            )
        )
    return tuple(artifacts)


class MarkdownAnalyzer:
    """
    Concrete Markdown analyzer for repository documentation indexing.

    Parameters
    ----------
    None

    Notes
    -----
    Markdown files emit documentation artifacts only. The module artifact is a
    file identity carrier required by the shared analyzer result contract.
    """

    name = "markdown"
    version = "1"
    discovery_globs: tuple[str, ...] = ("*.md",)

    def __init__(self) -> None:
        self._path_filters = AnalyzerPathFilters()
        self._strip_front_matter = True
        self._emit_file_artifact_without_headings = True
        self._min_heading_level = 1
        self._max_heading_level = 6
        self.configuration_fingerprint = plugin_configuration_fingerprint({})

    def configuration_json_schema(self) -> Mapping[str, object]:
        """
        Return the Markdown analyzer configuration schema.

        Parameters
        ----------
        None

        Returns
        -------
        collections.abc.Mapping[str, object]
            Strict JSON Schema for Markdown analyzer options.
        """

        heading_level_property = {"type": "integer", "minimum": 1, "maximum": 6}
        return analyzer_json_schema(
            {
                "strip_front_matter": boolean_property(True),
                "emit_file_artifact_without_headings": boolean_property(True),
                "min_heading_level": {**heading_level_property, "default": 1},
                "max_heading_level": {**heading_level_property, "default": 6},
            }
        )

    def configure(self, config: Mapping[str, object]) -> None:
        """
        Apply Markdown analyzer configuration.

        Parameters
        ----------
        config : collections.abc.Mapping[str, object]
            Namespaced analyzer configuration table.

        Returns
        -------
        None
            Analyzer options are stored on this instance.

        Raises
        ------
        TypeError
            If heading level values are not integers.
        ValueError
            If the minimum heading level is greater than the maximum heading
            level.
        """

        self._path_filters = analyzer_path_filters_from_config(config)
        self._strip_front_matter = bool(config.get("strip_front_matter", True))
        self._emit_file_artifact_without_headings = bool(
            config.get("emit_file_artifact_without_headings", True)
        )
        min_heading_level = config.get("min_heading_level", 1)
        max_heading_level = config.get("max_heading_level", 6)
        if not isinstance(min_heading_level, int) or not isinstance(
            max_heading_level, int
        ):
            msg = "min_heading_level and max_heading_level must be integers."
            raise TypeError(msg)
        self._min_heading_level = min_heading_level
        self._max_heading_level = max_heading_level
        if self._min_heading_level > self._max_heading_level:
            msg = "min_heading_level must be <= max_heading_level."
            raise ValueError(msg)
        self.configuration_fingerprint = plugin_configuration_fingerprint(config)

    def analyzer_capability_declaration(self) -> AnalyzerCapabilityDeclaration:
        """
        Return Markdown analyzer ontology coverage.

        Parameters
        ----------
        None

        Returns
        -------
        codira.contracts.AnalyzerCapabilityDeclaration
            Explicit mapping from Markdown sections to documentation artifacts.
        """
        return AnalyzerCapabilityDeclaration(
            analyzer_name=self.name,
            analyzer_version=self.version,
            source="first_party",
            entrypoint="codira_analyzer_markdown:build_analyzer",
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
                "markdown_section": "documentation",
            },
        )

    def supports_path(self, path: Path) -> bool:
        """
        Decide whether the analyzer accepts a Markdown path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.

        Returns
        -------
        bool
            ``True`` when the path has a Markdown suffix.
        """
        return path.suffix.lower() == ".md"

    def allows_path(self, path: Path, root: Path) -> bool:
        """
        Decide whether configured path filters allow a supported Markdown path.

        Parameters
        ----------
        path : pathlib.Path
            Candidate repository file.
        root : pathlib.Path
            Repository root used for relative path evaluation.

        Returns
        -------
        bool
            ``True`` when the path is allowed by include/exclude filters.
        """

        return analyzer_path_allowed(path=path, root=root, filters=self._path_filters)

    def analyze_file(self, path: Path, root: Path) -> AnalysisResult:
        """
        Analyze one Markdown file into documentation artifacts.

        Parameters
        ----------
        path : pathlib.Path
            Markdown source file.
        root : pathlib.Path
            Repository root used for relative identity derivation.

        Returns
        -------
        codira.models.AnalysisResult
            Analysis result carrying deterministic documentation artifacts.
        """
        module = ModuleArtifact(
            name=_module_name_for_path(path, root),
            stable_id=_module_stable_id(path, root),
            docstring=None,
            has_docstring=0,
        )
        return AnalysisResult(
            source_path=path,
            module=module,
            classes=(),
            functions=(),
            declarations=(),
            imports=(),
            documentation=_documentation_artifacts(
                path,
                root,
                strip_front_matter=self._strip_front_matter,
                emit_file_artifact_without_headings=(
                    self._emit_file_artifact_without_headings
                ),
                min_heading_level=self._min_heading_level,
                max_heading_level=self._max_heading_level,
            ),
            index_symbols=False,
        )


def build_analyzer() -> LanguageAnalyzer:
    """
    Build the first-party Markdown analyzer plugin instance.

    Parameters
    ----------
    None

    Returns
    -------
    codira.contracts.LanguageAnalyzer
        Fresh Markdown analyzer instance for registry discovery.
    """
    return MarkdownAnalyzer()
