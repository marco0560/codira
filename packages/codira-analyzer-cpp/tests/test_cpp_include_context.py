"""Exercise source-contained include snapshots and dependency invalidation.

Parameters
----------
None

Returns
-------
None
    Behavioral checks without compiler or build-tool execution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from codira_analyzer_cpp.cpp_include_context import (
    include_identity_matches,
    read_include_context,
)
from codira_analyzer_cpp.cpp_preprocessing import _parse_cpp_source


def test_transitive_graph_cycles_and_first_availability(tmp_path: Path) -> None:
    """Keep transitive snapshots once and use their earliest include boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Cycles terminate and later direct includes do not delay availability.
    """
    source = b'#include "a.h"\n#include "b.h"\nint value;\n'
    (tmp_path / "main.cpp").write_bytes(source)
    (tmp_path / "a.h").write_bytes(b'#include "b.h"\n')
    (tmp_path / "b.h").write_bytes(b'#include "main.cpp"\n#include "c.h"\n')
    (tmp_path / "c.h").write_bytes(b"#define API\n")
    context = read_include_context(tmp_path / "main.cpp", tmp_path)
    assert context.source == source
    assert {item.path.name for item in context.headers} == {"a.h", "b.h", "c.h"}
    assert {item.available_after for item in context.headers} == {
        len(b'#include "a.h"\n')
    }
    assert context.unresolved == ()


def test_dependency_bytes_change_fingerprint_despite_same_stat(tmp_path: Path) -> None:
    """Hash header bytes independently of source bytes, mtime and size.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Equal-size edits with restored times invalidate the dependency digest.
    """
    path = tmp_path / "main.cpp"
    path.write_bytes(b'#include "api.h"\nAPI int value();\n')
    header = tmp_path / "api.h"
    header.write_bytes(b"#define API a\n")
    original = read_include_context(path, tmp_path)
    stat = header.stat()
    header.write_bytes(b"#define API b\n")
    os.utime(header, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = read_include_context(path, tmp_path)
    assert original.source == changed.source == path.read_bytes()
    assert original.fingerprint != changed.fingerprint
    assert original.headers[0].source == b"#define API a\n"


def test_missing_creation_deletion_and_search_precedence(tmp_path: Path) -> None:
    """Record negative lookups and honor explicit compiler-style search order.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        New, removed and shadowing headers change dependency identity.
    """
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    include_dir = tmp_path / "include"
    include_dir.mkdir()
    path = source_dir / "main.cpp"
    path.write_bytes(b'#include "api.h"\n')
    missing = read_include_context(path, tmp_path, include_paths=(Path("include"),))
    assert missing.unresolved == (("src/main.cpp", "api.h", "missing"),)
    (include_dir / "api.h").write_bytes(b"#define API\n")
    found = read_include_context(path, tmp_path, include_paths=(include_dir,))
    assert found.headers[0].path == include_dir / "api.h"
    (source_dir / "api.h").write_bytes(b"#define API private\n")
    shadowed = read_include_context(path, tmp_path, include_paths=(include_dir,))
    assert shadowed.headers[0].path == source_dir / "api.h"
    (source_dir / "api.h").unlink()
    restored = read_include_context(path, tmp_path, include_paths=(include_dir,))
    assert restored.fingerprint == found.fingerprint
    assert len({missing.fingerprint, found.fingerprint, shadowed.fingerprint}) == 3


def test_directives_in_branches_exclude_comment_and_literal_text(
    tmp_path: Path,
) -> None:
    """Retain both source branches while ignoring directive-shaped trivia.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Branches and unresolved macro includes remain explicit.
    """
    path = tmp_path / "main.cpp"
    path.write_bytes(b"""// #include "fake.h"
const char *text = R"x(
#include "fake2.h"
)x";
#if PLATFORM
#include "a.h"
#else
#include "b.h"
#endif
#include HEADER
""")
    (tmp_path / "a.h").write_bytes(b"#define API\n")
    (tmp_path / "b.h").write_bytes(b"#define API __declspec(dllexport)\n")
    context = read_include_context(path, tmp_path)
    assert {item.path.name for item in context.headers} == {"a.h", "b.h"}
    assert context.unresolved == (("main.cpp", "HEADER", "macro"),)


def test_system_search_requires_explicit_roots(tmp_path: Path) -> None:
    """Avoid guessing repository include roots or consulting host headers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Only explicitly supplied roots resolve system includes.
    """
    path = tmp_path / "main.cpp"
    path.write_bytes(b"#include <api.h>\n#include <vector>\n")
    (tmp_path / "api.h").write_bytes(b"#define API\n")
    unresolved = read_include_context(path, tmp_path)
    assert not unresolved.headers
    assert {item[2] for item in unresolved.unresolved} == {"external"}
    resolved = read_include_context(path, tmp_path, include_paths=(Path("."),))
    assert [item.path.name for item in resolved.headers] == ["api.h"]
    assert resolved.unresolved == (("main.cpp", "vector", "missing"),)


def test_escape_and_symlink_targets_stay_outside_snapshot(tmp_path: Path) -> None:
    """Reject dependencies and search roots outside the repository boundary.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and sibling fixtures.

    Returns
    -------
    None
        Parent traversal and symlinks cannot import external file contents.
    """
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.h"
    outside.write_bytes(b"#define API secret\n")
    (root / "alias.h").symlink_to(outside)
    path = root / "main.cpp"
    path.write_bytes(b'#include "../outside.h"\n#include "alias.h"\n')
    context = read_include_context(path, root)
    assert not context.headers
    assert len(context.unresolved) == 2
    assert {item[2] for item in context.unresolved} == {"outside_root"}
    with pytest.raises(ValueError, match="inside the repository"):
        read_include_context(path, root, include_paths=(tmp_path,))
    with pytest.raises(ValueError, match="inside the repository"):
        read_include_context(outside, root)


def test_relative_root_and_transitive_parent_include(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolve each quoted include relative to its own including file.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    monkeypatch : pytest.MonkeyPatch
        Isolated working-directory change.

    Returns
    -------
    None
        Relative root spelling does not alter the resulting identity.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "inc").mkdir()
    path = tmp_path / "src/main.cpp"
    path.write_bytes(b'#include "../inc/api.h"\n')
    (tmp_path / "inc/api.h").write_bytes(b'#include "base.h"\n')
    (tmp_path / "inc/base.h").write_bytes(b"#define API\n")
    absolute = read_include_context(path, tmp_path)
    monkeypatch.chdir(tmp_path)
    relative = read_include_context(Path("src/main.cpp"), Path("."))
    assert absolute == relative


@pytest.mark.parametrize(
    ("header", "prefix", "recover"),
    [
        (b"#define API [[nodiscard]]\n", b"", True),
        (b"#define ATTR [[nodiscard]]\n#define API ATTR\n", b"", True),
        (
            b"#if WINDOWS\n#define API __declspec(dllexport)\n#else\n#define API\n#endif\n",
            b"",
            True,
        ),
        (b"#define API\n", b"#define API Widget\n", False),
        (b"#define API\n#undef API\n", b"", False),
        (b"#define API(x) x\n", b"", False),
        (b"#if FEATURE\n#define API\n#else\n#define API Widget\n#endif\n", b"", False),
        (b"#define API int\n", b"", False),
        (b"#define API static\n", b"", False),
    ],
)
def test_header_annotation_projection_keeps_source_coordinates(
    tmp_path: Path, header: bytes, prefix: bytes, recover: bool
) -> None:
    """Use captured compatible definitions without copying header declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    header : bytes
        Annotation definitions or incompatible replacement witnesses.
    prefix : bytes
        Source-local definitions participating in conflict detection.
    recover : bool
        Whether every observed replacement licenses annotation recovery.

    Returns
    -------
    None
        Only compatible annotations yield a clean tree at original offsets.
    """
    path = tmp_path / "main.cpp"
    source = prefix + b'#include "api.h"\nAPI int run() { return callee(); }\n'
    path.write_bytes(source)
    (tmp_path / "api.h").write_bytes(header + b"int header_only();\n")
    context = read_include_context(path, tmp_path)
    root = _parse_cpp_source(
        context.source,
        included_sources=tuple(
            (item.source, item.available_after) for item in context.headers
        ),
    )
    assert root.has_error is not recover
    assert path.read_bytes() == source
    if recover:
        assert b"header_only" not in (root.text or b"")
        function = root.named_children[-1]
        body = function.child_by_field_name("body")
        assert body is not None
        assert source[body.start_byte : body.end_byte] == b"{ return callee(); }"


def test_transitive_annotations_cannot_recover_uses_before_include(
    tmp_path: Path,
) -> None:
    """Respect source include boundaries even for transitive aliases.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Earlier uses remain errors; later uses recover without header symbols.
    """
    path = tmp_path / "main.cpp"
    (tmp_path / "api.h").write_bytes(b'#include "base.h"\n#define API ATTR\n')
    (tmp_path / "base.h").write_bytes(b"#define ATTR [[nodiscard]]\n")
    for before in (True, False):
        use = b"API int run() { return 1; }\n"
        include = b'#include "api.h"\n'
        path.write_bytes(use + include if before else include + use)
        context = read_include_context(path, tmp_path)
        root = _parse_cpp_source(
            context.source,
            included_sources=tuple(
                (item.source, item.available_after) for item in context.headers
            ),
        )
        assert root.has_error is before


def test_fast_identity_checks_resolution_shadowing_and_symlink_changes(
    tmp_path: Path,
) -> None:
    """Invalidate captured lookup choices even when old header bytes survive.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository and explicit include roots.

    Returns
    -------
    None
        Shadowing and symlink retargeting are detected independently of bytes.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "include").mkdir()
    source = tmp_path / "src/main.cpp"
    source.write_bytes(b'#include "api.h"\nAPI int run();\n')
    header = tmp_path / "include/api.h"
    header.write_bytes(b"#define API\n")
    context = read_include_context(source, tmp_path, include_paths=(Path("include"),))
    assert include_identity_matches(source, tmp_path, context.identity)
    shadow = tmp_path / "src/api.h"
    shadow.write_bytes(header.read_bytes())
    assert not include_identity_matches(source, tmp_path, context.identity)
    shadow.unlink()
    assert include_identity_matches(source, tmp_path, context.identity)
    alias = tmp_path / "src/alias.h"
    other = tmp_path / "include/other.h"
    other.write_bytes(header.read_bytes())
    alias.symlink_to(header)
    source.write_bytes(b'#include "alias.h"\nAPI int run();\n')
    captured = read_include_context(source, tmp_path)
    assert include_identity_matches(source, tmp_path, captured.identity)
    alias.unlink()
    alias.symlink_to(other)
    assert not include_identity_matches(source, tmp_path, captured.identity)


def test_fast_identity_rejects_corrupt_or_escaping_manifest(tmp_path: Path) -> None:
    """Require a complete contained manifest before approving incremental reuse.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Invalid identities cannot produce a fresh result.
    """
    source = tmp_path / "main.cpp"
    source.write_bytes(b'#include "api.h"\nAPI int run();\n')
    header = tmp_path / "api.h"
    header.write_bytes(b"#define API\n")
    context = read_include_context(source, tmp_path)
    assert include_identity_matches(source, tmp_path, context.identity)
    for identity in ("", "legacy-digest", "{}", "[]", '{"format": 999}'):
        assert not include_identity_matches(source, tmp_path, identity)
    payload = json.loads(context.identity)
    payload["headers"] = []
    assert not include_identity_matches(source, tmp_path, json.dumps(payload))
    payload["source_path"] = "../outside.cpp"
    assert not include_identity_matches(source, tmp_path, json.dumps(payload))
    source.write_bytes(source.read_bytes() + b"int added;\n")
    assert not include_identity_matches(source, tmp_path, context.identity)
