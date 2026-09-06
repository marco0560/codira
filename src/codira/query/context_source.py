"""Focused context-query responsibility module."""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import TYPE_CHECKING

from codira.query.context_models import (
    DOCSTRING_PREVIEW_LINE_LIMIT,
    DOCUMENTATION_DOCS_PATH_BONUS,
    DOCUMENTATION_NAMED_DOC_BONUS,
    DOCUMENTATION_SPECIAL_PATH_BONUS,
    SNIPPET_LINE_LIMIT,
    FileRole,
    _ReferenceScanFile,
)
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codira.query.classifier import QueryIntent
    from codira.types import (
        ChannelResults,
        CodeContext,
        ReferenceRow,
        ReferenceSearchRow,
        SymbolRow,
    )


def _symbol_sort_key(symbol: SymbolRow) -> tuple[str, str, str, int, str]:
    """
    Return a deterministic ascending sort key for a symbol row.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Symbol row to normalize into a sortable key.

    Returns
    -------
    tuple[str, str, str, int, str]
        Deterministic ascending key based on module, name, file, line, and type.
    """
    symbol_type, module_name, name, file_path, lineno = symbol
    return (module_name, name, file_path, lineno, symbol_type)


def _scored_symbol_sort_key(
    item: tuple[float, SymbolRow],
) -> tuple[float, str, str, str, int, str]:
    """
    Return a deterministic sort key for scored symbols.

    Parameters
    ----------
    item : tuple[float, codira.types.SymbolRow]
        Score and symbol pair to normalize.

    Returns
    -------
    tuple[float, str, str, str, int, str]
        Sort key ordering by descending score and ascending symbol identity.
    """
    score, symbol = item
    module_name, name, file_path, lineno, symbol_type = _symbol_sort_key(symbol)
    return (-score, module_name, name, file_path, lineno, symbol_type)


def _dedupe_channel_results(channel: ChannelResults) -> ChannelResults:
    """
    Remove duplicate symbols from a single channel while keeping best rank.

    Parameters
    ----------
    channel : codira.types.ChannelResults
        Ranked results emitted by one retrieval channel.

    Returns
    -------
    codira.types.ChannelResults
        Deduplicated channel results preserving the first occurrence of each
        symbol.
    """
    seen: set[SymbolRow] = set()
    deduped: ChannelResults = []

    for score, symbol in channel:
        if symbol in seen:
            continue
        seen.add(symbol)
        deduped.append((score, symbol))

    return deduped


def _source_indentation(line: str) -> int:
    """
    Return the leading indentation width for one source line.

    Parameters
    ----------
    line : str
        Source line whose indentation is measured.

    Returns
    -------
    int
        Count of leading whitespace characters.
    """
    return len(line) - len(line.lstrip())


def _source_header_end(source_lines: Sequence[str], start: int) -> int:
    """Return the exclusive source-line boundary of one declaration header.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Complete source file split into lines.
    start : int
        Zero-based declaration start line.

    Returns
    -------
    int
        Exclusive line index containing the declaration header.
    """
    depth = 0
    for index in range(start, len(source_lines)):
        for character in source_lines[index]:
            if character in "([{":
                depth += 1
            elif character in ")]}":
                depth = max(depth - 1, 0)
            elif character == ":" and depth == 0:
                return index + 1
    return min(start + 1, len(source_lines))


def _source_docstring(
    source_lines: Sequence[str], start: int, end: int
) -> tuple[str | None, tuple[int, int] | None]:
    """Return a leading triple-quoted documentation block from source text.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Complete source file split into lines.
    start : int
        Zero-based line at which to begin looking for documentation.
    end : int
        Exclusive source boundary for the owning module or declaration.

    Returns
    -------
    tuple[str | None, tuple[int, int] | None]
        Cleaned documentation text and its zero-based half-open line range, or
        ``(None, None)`` when no leading documentation block exists.
    """
    candidate = start
    while candidate < end and (
        not source_lines[candidate].strip()
        or source_lines[candidate].lstrip().startswith("#")
    ):
        candidate += 1
    if candidate >= end:
        return (None, None)
    match = re.match(r"^\s*(?:[rubRUB]{0,2})?(\"\"\"|''')", source_lines[candidate])
    if match is None:
        return (None, None)
    delimiter = match.group(1)
    content_start = source_lines[candidate].find(delimiter) + len(delimiter)
    remaining = source_lines[candidate][content_start:]
    closing = remaining.find(delimiter)
    if closing >= 0:
        return (inspect.cleandoc(remaining[:closing]), (candidate, candidate + 1))
    content = [remaining]
    for index in range(candidate + 1, end):
        closing = source_lines[index].find(delimiter)
        if closing >= 0:
            content.append(source_lines[index][:closing])
            return (inspect.cleandoc("\n".join(content)), (candidate, index + 1))
        content.append(source_lines[index])
    return (None, None)


def _source_declaration_range(
    source_lines: Sequence[str], lineno: int
) -> tuple[int, int] | None:
    """Return the source range occupied by an indexed declaration.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Complete source file split into lines.
    lineno : int
        One-based declaration line from the persisted artifact.

    Returns
    -------
    tuple[int, int] | None
        Zero-based half-open declaration range, or ``None`` when the indexed
        line no longer identifies a declaration in the current source.
    """
    start = lineno - 1
    if start < 0 or start >= len(source_lines):
        return None
    declaration = source_lines[start].lstrip()
    if not re.match(r"(?:async\s+def|def|class)\s+", declaration):
        return None
    indentation = _source_indentation(source_lines[start])
    header_end = _source_header_end(source_lines, start)
    end = len(source_lines)
    for index in range(header_end, len(source_lines)):
        line = source_lines[index]
        if line.strip() and _source_indentation(line) <= indentation:
            end = index
            break
    return (start, end)


def _source_decorator_start(source_lines: Sequence[str], start: int) -> int:
    """Return the first contiguous decorator line before a declaration.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Complete source file split into lines.
    start : int
        Zero-based declaration start line.

    Returns
    -------
    int
        Zero-based start line including contiguous decorators at the declaration
        indentation level.
    """
    indentation = _source_indentation(source_lines[start])
    decorator_start = start
    while decorator_start > 0:
        previous = source_lines[decorator_start - 1]
        if _source_indentation(
            previous
        ) != indentation or not previous.lstrip().startswith("@"):
            break
        decorator_start -= 1
    return decorator_start


def _render_source_signature(source_lines: Sequence[str], start: int) -> str | None:
    """Render a compact class or callable signature from its source header.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Complete source file split into lines.
    start : int
        Zero-based declaration start line.

    Returns
    -------
    str | None
        Compact signature text, or ``None`` when the line is not a supported
        declaration header.
    """
    header_end = _source_header_end(source_lines, start)
    header = " ".join(line.strip() for line in source_lines[start:header_end])
    if header.startswith("class "):
        match = re.match(r"class\s+([A-Za-z_]\w*)", header)
        return None if match is None else match.group(1)
    match = re.match(r"(?:(async)\s+)?def\s+([A-Za-z_]\w*)\s*(.*)", header)
    if match is None:
        return None
    suffix = match.group(3)
    if suffix.endswith(":"):
        suffix = suffix[:-1].rstrip()
    prefix = "async " if match.group(1) else ""
    return f"{prefix}{match.group(2)}{suffix}"


def _truncate_lines(text: str | None, limit: int) -> str | None:
    """
    Truncate multiline text to a fixed number of lines.

    Parameters
    ----------
    text : str | None
        Text block to truncate.
    limit : int
        Maximum number of lines to retain before appending an ellipsis line.

    Returns
    -------
    str | None
        Truncated text, or ``None`` when the input is empty.
    """
    if not text:
        return None

    lines = text.strip().splitlines()
    if len(lines) <= limit:
        return "\n".join(lines)

    kept = lines[:limit]
    kept.append("...")
    return "\n".join(kept)


def _snippet_from_lines(
    source_lines: list[str], lineno: int, limit: int = SNIPPET_LINE_LIMIT
) -> list[str]:
    """
    Slice a fixed-size snippet from raw source lines.

    Parameters
    ----------
    source_lines : list[str]
        Source file split into lines.
    lineno : int
        One-based line number at which the snippet should start.
    limit : int, optional
        Maximum number of lines to return.

    Returns
    -------
    list[str]
        Right-stripped source lines for the requested slice.
    """
    start = max(lineno - 1, 0)
    end = min(start + limit, len(source_lines))
    return [line.rstrip() for line in source_lines[start:end]]


def _normalize_snippet_lines(lines: Sequence[str], limit: int) -> list[str]:
    """
    Normalize snippet lines for readable deterministic display.

    Parameters
    ----------
    lines : list[str]
        Raw snippet lines.
    limit : int
        Maximum number of normalized lines to retain.

    Returns
    -------
    list[str]
        Snippet lines with trailing whitespace removed, edge blanks trimmed,
        and repeated blank lines collapsed.
    """
    normalized: list[str] = []
    previous_blank = False

    for raw_line in lines:
        line = raw_line.rstrip()
        is_blank = line == ""

        if is_blank and previous_blank:
            continue

        normalized.append(line)
        previous_blank = is_blank

    while normalized and normalized[0] == "":
        normalized.pop(0)

    while normalized and normalized[-1] == "":
        normalized.pop()

    return normalized[:limit]


def _snippet_from_source_range(
    source_lines: Sequence[str],
    source_range: tuple[int, int],
    docstring_range: tuple[int, int] | None,
    limit: int = SNIPPET_LINE_LIMIT,
) -> list[str]:
    """
    Extract a compact snippet from persisted source ranges.

    Parameters
    ----------
    source_lines : collections.abc.Sequence[str]
        Source file split into lines.
    source_range : tuple[int, int]
        Zero-based half-open declaration range.
    docstring_range : tuple[int, int] | None
        Optional zero-based half-open range to omit from the snippet.
    limit : int, optional
        Maximum number of snippet lines to retain.

    Returns
    -------
    list[str]
        Normalized snippet lines for the node.

    Notes
    -----
    Leading documentation blocks are removed from the snippet so the reader
    sees executable structure first.
    """
    start, end = source_range
    snippet = source_lines[start:end]
    if docstring_range is not None:
        doc_start, doc_end = docstring_range
        snippet = [
            line
            for index, line in enumerate(snippet, start=start)
            if not (doc_start <= index < doc_end)
        ]
    return _normalize_snippet_lines(snippet, limit)


def _load_cached_source_file(
    path: Path,
    cache: dict[Path, tuple[str, list[str]]],
    *,
    max_source_file_bytes: int,
) -> tuple[str, list[str]] | None:
    """
    Load and cache one source file used for context rendering.

    Parameters
    ----------
    path : pathlib.Path
        Absolute source path to load.
    cache : dict[pathlib.Path, tuple[str, list[str]]]
        Parsed-file cache shared across multiple lookups.
    max_source_file_bytes : int
        Command-scoped source-ingestion byte ceiling.

    Returns
    -------
    tuple[str, list[str]] | None
        Cached source and split lines. Returns ``None`` when the file cannot
        be read.
    """
    if path in cache:
        return cache[path]

    try:
        if path.stat().st_size > max_source_file_bytes:
            return None
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    cached = (source, source.splitlines())
    cache[path] = cached
    return cached


def _extract_code_context(
    root: Path,
    symbol: SymbolRow,
    cache: dict[Path, tuple[str, list[str]]],
    *,
    max_source_file_bytes: int,
) -> CodeContext:
    """
    Extract signature, docstring, and snippet data for a symbol.

    Parameters
    ----------
    root : pathlib.Path
        Repository root used to resolve file paths.
    symbol : codira.types.SymbolRow
        Indexed symbol row to expand.
    cache : dict[pathlib.Path, tuple[str, list[str]]]
        Source-file cache shared across multiple lookups.
    max_source_file_bytes : int
        Command-scoped source-ingestion byte ceiling.

    Returns
    -------
    codira.types.CodeContext
        Signature, truncated docstring, and code snippet for the symbol.
    """
    symbol_type, _module_name, name, file_path, lineno = symbol
    path = Path(file_path)
    if not path.is_absolute():
        path = root / path

    loaded = _load_cached_source_file(
        path,
        cache,
        max_source_file_bytes=max_source_file_bytes,
    )
    if loaded is None:
        return (None, None, [])

    _source, source_lines = loaded

    if symbol_type == "module":
        docstring, _docstring_range = _source_docstring(
            source_lines, 0, len(source_lines)
        )
        return (
            None,
            _truncate_lines(docstring, DOCSTRING_PREVIEW_LINE_LIMIT),
            _snippet_from_lines(source_lines, lineno),
        )

    if symbol_type in {"class", "function", "method"}:
        source_range = _source_declaration_range(source_lines, lineno)
        if source_range is not None:
            start, end = source_range
            docstring, docstring_range = _source_docstring(
                source_lines,
                _source_header_end(source_lines, start),
                end,
            )
            return (
                _render_source_signature(source_lines, start),
                _truncate_lines(docstring, DOCSTRING_PREVIEW_LINE_LIMIT),
                _snippet_from_source_range(
                    source_lines,
                    (_source_decorator_start(source_lines, start), end),
                    docstring_range,
                ),
            )

    return (None, None, _snippet_from_lines(source_lines, lineno))


def _symbols_in_module(
    root: Path,
    module: str,
    *,
    prefix: str | None = None,
) -> list[SymbolRow]:
    """
    Retrieve indexed symbols belonging to a module.

    Parameters
    ----------
    root : pathlib.Path
        Repository root containing the index database.
    module : str
        Dotted module name to expand.
    prefix : str | None, optional
        Repo-root-relative path prefix used to restrict symbol files.

    Returns
    -------
    list[codira.types.SymbolRow]
        Up to twenty indexed symbols from the requested module.
    """
    backend = active_index_backend(root=root)
    return backend.list_symbols_in_module(
        root,
        module,
        prefix=prefix,
        limit=20,
    )


def _find_references(
    name: str,
    reference_rows: list[ReferenceSearchRow],
) -> list[ReferenceRow]:
    """
    Reduce stored reference-search rows to plain reference locations.

    Parameters
    ----------
    name : str
        Symbol name to search for.
    reference_rows : list[codira.types.ReferenceSearchRow]
        Stored query-time rows to filter.

    Returns
    -------
    list[codira.types.ReferenceRow]
        Reference locations as ``(file_path, lineno)`` tuples.

    Notes
    -----
    The function preserves the current simple substring containment semantics
    and global cap while letting the backend own stored source-line retrieval.
    """
    results: list[ReferenceRow] = []
    for file_path, lineno, line_text in reference_rows:
        if name not in line_text:
            continue

        results.append((file_path, lineno))

        if len(results) >= 50:
            return results

    return results


def _load_reference_scan_file(
    path: Path,
    file_cache: dict[Path, _ReferenceScanFile],
) -> _ReferenceScanFile | None:
    """
    Load and cache the reusable reference-scan view for one file.

    Parameters
    ----------
    path : pathlib.Path
        Project file to decode for reference scanning.
    file_cache : dict[pathlib.Path, codira.query.context._ReferenceScanFile]
        In-memory cache reused across symbol-name scans.

    Returns
    -------
    codira.query.context._ReferenceScanFile | None
        Cached scan view, or ``None`` when the file cannot be decoded.
    """
    cached = file_cache.get(path)
    if cached is not None:
        return cached

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    searchable_lines = tuple(
        (lineno, line)
        for lineno, line in enumerate(text.splitlines(), start=1)
        if not line.strip().startswith(("import ", "from "))
    )
    cached = _ReferenceScanFile(
        file_path=str(path),
        text=text,
        searchable_lines=searchable_lines,
    )
    file_cache[path] = cached
    return cached


def _tokenize(text: str) -> set[str]:
    """
    Tokenize text into lowercased alphanumeric and underscore fragments.

    Parameters
    ----------
    text : str
        Input text to split.

    Returns
    -------
    set[str]
        Unique normalized tokens extracted from the input.
    """
    parts = re.split(r"[^A-Za-z0-9_]+", text.lower())
    tokens: set[str] = set()

    for part in parts:
        if not part:
            continue

        tokens.add(part)
        for sub in part.split("_"):
            if sub:
                tokens.add(sub)

    return tokens


def _classify_file_role(file_path: str, module_name: str) -> FileRole:
    """
    Classify one indexed file into a deterministic retrieval role.

    Parameters
    ----------
    file_path : str
        Indexed file path for the candidate symbol.
    module_name : str
        Indexed module name owning the candidate symbol.

    Returns
    -------
    {"implementation", "interface", "test", "tooling", "other"}
        Deterministic file role used by retrieval scoring.
    """
    path_obj = Path(file_path)
    lowered_parts = {part.lower() for part in path_obj.parts}
    lowered_name = path_obj.name.lower()
    lowered_module = module_name.lower()

    if (
        "tests" in lowered_parts
        or lowered_name.startswith("test_")
        or lowered_module.startswith("tests.")
    ):
        return "test"

    if lowered_module.startswith("scripts.") or any(
        part in lowered_parts for part in {"scripts", "tools", "bin"}
    ):
        return "tooling"

    if path_obj.suffix == ".h":
        return "interface"

    if path_obj.suffix in {".c", ".py"}:
        return "implementation"

    return "other"


def _file_role_bias(role: FileRole, intent: QueryIntent | None = None) -> int:
    """
    Return the retrieval bias associated with one file role.

    Parameters
    ----------
    role : {"implementation", "interface", "test", "tooling", "other"}
        Deterministic file role for the candidate symbol.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to flip test or tooling preferences when explicit.

    Returns
    -------
    int
        Small deterministic additive ranking bias.
    """
    if role == "implementation":
        return (
            1 if intent and (intent.is_test_related or intent.is_script_related) else 3
        )

    if role == "interface":
        return 2

    if role == "test":
        return 4 if intent and intent.is_test_related else -4

    if role == "tooling":
        return 4 if intent and intent.is_script_related else -5

    return 0


def _documentation_docs_path_bonus(
    symbol: SymbolRow,
    channel_scores: dict[str, float],
) -> float:
    """
    Return the small ranking bonus for docs-channel artifacts under ``docs/``.

    Parameters
    ----------
    symbol : codira.types.SymbolRow
        Candidate symbol or documentation-shaped row.
    channel_scores : dict[str, float]
        Weighted channel scores that contributed to the candidate.

    Returns
    -------
    float
        Small additive score for documentation artifacts under a ``docs`` path.
    """
    if symbol[0] != "documentation" or "docs" not in channel_scores:
        return 0.0
    path = Path(symbol[3])
    parts = tuple(part.lower() for part in path.parts)
    stem = path.stem.lower()

    if stem in {"readme", "changelog"}:
        return DOCUMENTATION_NAMED_DOC_BONUS
    if "docs" in parts and ("process" in parts or "adr" in parts):
        return DOCUMENTATION_SPECIAL_PATH_BONUS
    if "docs" in parts:
        return DOCUMENTATION_DOCS_PATH_BONUS
    return 0.0


def _path_bias(
    file_path: str,
    module_name: str,
    *,
    intent: QueryIntent | None = None,
) -> int:
    """
    Lightweight ranking bias based on file location.

    Parameters
    ----------
    file_path : str
        Indexed file path for the candidate symbol.
    module_name : str
        Indexed module name owning the candidate symbol.
    intent : codira.query.classifier.QueryIntent | None, optional
        Query intent used to flip test and tooling preferences when explicit.

    Returns
    -------
    int
        Small additive score bias based on the file location.

    Notes
    -----
    The bias prefers source files over scripts and tests without suppressing
    those results entirely.
    """
    role = _classify_file_role(file_path, module_name)
    return _file_role_bias(role, intent)
