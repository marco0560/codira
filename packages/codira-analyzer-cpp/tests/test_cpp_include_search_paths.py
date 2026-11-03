"""Verify configured include roots, extraction and dependency-aware reuse.

Parameters
----------
None

Returns
-------
None
    Exercises actual analyzer and backend behavior with contained headers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from codira_analyzer_cpp import CppAnalyzer

from codira.indexer import index_repo
from codira.query.exact import symbol_inventory
from codira.registry import active_index_backend


@pytest.fixture
def annotated_source(tmp_path: Path) -> Path:
    """Create an annotation header outside the source file's own directory.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository boundary.

    Returns
    -------
    pathlib.Path
        Source requiring an explicit include search root.
    """
    include = tmp_path / "include"
    include.mkdir()
    (include / "api.h").write_text("#define API __attribute__((cold))\n")
    source = tmp_path / "main.cpp"
    source.write_text(
        "#include <api.h>\nint callee(int);\n"
        "API int entry(int value) { return callee(value); }\n"
    )
    return source


def test_include_search_roots_recover_original_artifacts(
    annotated_source: Path,
) -> None:
    """Recover source signatures and calls using the configured header bytes.

    Parameters
    ----------
    annotated_source : pathlib.Path
        Translation unit and sibling include directory.

    Returns
    -------
    None
        Explicit roots recover symbols and participate in input identity.
    """
    root = annotated_source.parent
    analyzer = CppAnalyzer()
    source_only = analyzer.analyze_file(annotated_source, root)
    assert source_only.index_symbols
    assert source_only.status is not None
    assert source_only.status.coverage_state.value == "partial"
    assert [item.name for item in source_only.functions] == ["callee"]
    analyzer.configure({"include_search_paths": ["include"]})
    result = analyzer.analyze_file(annotated_source, root)
    assert result.index_symbols
    entry = next(item for item in result.functions if item.name == "entry")
    assert entry.lineno == 3
    assert entry.signature.startswith("API int entry")
    assert any(call.target == "callee" for call in entry.calls)
    identity = analyzer.analysis_input_fingerprint(annotated_source, root)
    assert json.loads(identity)["search"] == ["include"]
    assert analyzer.analysis_input_fingerprint_matches(annotated_source, root, identity)


@pytest.mark.parametrize("invalid", [None, "include", [None], [3], [""], ("include",)])
def test_include_search_roots_reject_invalid_configuration(invalid: object) -> None:
    """Reject malformed configuration before attempting to read include files.

    Parameters
    ----------
    invalid : object
        Value outside the documented list-of-nonempty-strings contract.

    Returns
    -------
    None
        Configuration fails with a useful option-specific error.
    """
    with pytest.raises(ValueError, match="include_search_paths"):
        CppAnalyzer().configure({"include_search_paths": invalid})


def test_include_search_root_order_and_new_shadow_invalidate_reuse(
    annotated_source: Path,
) -> None:
    """Detect changes in lookup precedence even with unchanged source bytes.

    Parameters
    ----------
    annotated_source : pathlib.Path
        Source initially resolving its second search root.

    Returns
    -------
    None
        New earlier headers and reordered configuration invalidate reuse.
    """
    root = annotated_source.parent
    earlier = root / "first"
    earlier.mkdir()
    analyzer = CppAnalyzer()
    analyzer.configure({"include_search_paths": ["first", "include"]})
    identity = analyzer.analysis_input_fingerprint(annotated_source, root)
    (earlier / "api.h").write_bytes((root / "include/api.h").read_bytes())
    assert not analyzer.analysis_input_fingerprint_matches(
        annotated_source, root, identity
    )
    current = analyzer.analysis_input_fingerprint(annotated_source, root)
    analyzer.configure({"include_search_paths": ["include", "first"]})
    assert not analyzer.analysis_input_fingerprint_matches(
        annotated_source, root, current
    )


def test_include_search_root_symlink_retarget_invalidates_reuse(
    annotated_source: Path,
) -> None:
    """Observe the current search-root target rather than only captured paths.

    Parameters
    ----------
    annotated_source : pathlib.Path
        Owned source and initial header directory.

    Returns
    -------
    None
        Retargeting a configured symlink invalidates an otherwise identical input.
    """
    root = annotated_source.parent
    alternate = root / "alternate"
    alternate.mkdir()
    (alternate / "api.h").write_bytes((root / "include/api.h").read_bytes())
    link = root / "selected"
    link.symlink_to(root / "include", target_is_directory=True)
    analyzer = CppAnalyzer()
    analyzer.configure({"include_search_paths": ["selected"]})
    identity = analyzer.analysis_input_fingerprint(annotated_source, root)
    assert analyzer.analysis_input_fingerprint_matches(annotated_source, root, identity)
    link.unlink()
    link.symlink_to(alternate, target_is_directory=True)
    assert not analyzer.analysis_input_fingerprint_matches(
        annotated_source, root, identity
    )


def test_include_search_roots_remain_inside_repository(annotated_source: Path) -> None:
    """Reject escaping configured roots for both capture and reuse checks.

    Parameters
    ----------
    annotated_source : pathlib.Path
        Source inside the trusted boundary.

    Returns
    -------
    None
        External roots cannot read headers or validate old identities.
    """
    root = annotated_source.parent
    analyzer = CppAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    identity = analyzer.analysis_input_fingerprint(annotated_source, root)
    analyzer.configure({"include_search_paths": ["../outside"]})
    with pytest.raises(ValueError):
        analyzer.analysis_input_fingerprint(annotated_source, root)
    assert not analyzer.analysis_input_fingerprint_matches(
        annotated_source, root, identity
    )


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_include_search_roots_drive_actual_index_reuse_and_rebuild(
    annotated_source: Path, backend: str
) -> None:
    """Persist recovered functions and invalidate equal-stat header edits.

    Parameters
    ----------
    annotated_source : pathlib.Path
        Source and annotation header inside an owned repository.
    backend : str
        Actual structural backend used by the full indexer.

    Returns
    -------
    None
        Reuse, dependency invalidation and rebuild preserve the expected symbols.
    """
    root = annotated_source.parent
    (root / ".codira").mkdir()
    (root / ".codira/config.toml").write_text(
        f'config_version = 2\n[backend]\nname = "{backend}"\n'
        '[embeddings]\nenabled = false\nsimilarity_index = "exact"\n'
        '[plugins.analyzer-cpp]\ninclude_search_paths = ["include"]\n'
    )
    assert active_index_backend(root=root).name == backend
    first = index_repo(root)
    assert first.failed == 0
    assert "entry" in {item.name for item in symbol_inventory(root)}
    second = index_repo(root)
    assert second.indexed == 0 and second.reused == 2
    header = root / "include/api.h"
    stat = header.stat()
    header.write_text("#define API __attribute__((pure))\n")
    os.utime(header, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = index_repo(root)
    assert changed.indexed == 2 and changed.failed == 0
    expected = symbol_inventory(root)
    rebuilt = index_repo(root, full=True)
    assert rebuilt.failed == 0
    assert symbol_inventory(root) == expected
