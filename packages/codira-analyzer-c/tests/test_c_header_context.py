"""Verify explicit C header contexts, safe macro recovery and reuse identity.

Parameters
----------
None

Returns
-------
None
    Exercises real analyzer and indexer behavior against contained source inputs.
"""

import json
import os
from pathlib import Path

import pytest

from codira_analyzer_c import CAnalyzer
from codira.indexer import index_repo
from codira.query.exact import symbol_inventory


def _fixture(root: Path, header: str, source: str) -> Path:
    """Write one owned source/header fixture.

    Parameters
    ----------
    root : pathlib.Path
        Owned repository directory.
    header : str
        Captured header definitions.
    source : str
        Original translation-unit text.

    Returns
    -------
    pathlib.Path
        Source path inside the repository boundary.
    """
    (root / "include").mkdir(exist_ok=True)
    (root / "include/api.h").write_text(header)
    path = root / "main.c"
    path.write_bytes(source.encode())
    return path


def test_context_keeps_original_signature_and_positions(tmp_path: Path) -> None:
    """Recover only unsupported field prefixes while retaining source artifacts.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source and header boundary.

    Returns
    -------
    None
        Record identity, raw function signature and UTF-8 byte call position match.
    """
    source = (
        '#include "api.h"\r\n'
        "struct Record { LAYOUT int written; };\r\n"
        "FAST int run(int x) { /* café */ return callee(x); }\r\n"
    )
    path = _fixture(
        tmp_path, "#define LAYOUT int hidden;\n#define FAST inline\n", source
    )
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert any(d.name == "Record" and d.kind == "struct" for d in result.declarations)
    function = next(f for f in result.functions if f.name == "run")
    assert function.signature == "FAST int run(int x)"
    assert function.parameters == ("x",)
    assert len(function.calls) == 1
    call = function.calls[0]
    assert (call.kind, call.target, call.lineno, call.col_offset) == (
        "name",
        "callee",
        3,
        source.encode().splitlines()[2].index(b"callee"),
    )


@pytest.mark.parametrize("prefix", ["", "\ufeff"])
def test_preinclude_context_is_explicit(tmp_path: Path, prefix: str) -> None:
    """Use declared caller context before source without inferring it by filename.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source/header boundary.

    prefix : str
        Optional original UTF-8 BOM before the leading annotation.

    Returns
    -------
    None
        The absent source include is licensed only by explicit configuration.
    """
    path = _fixture(
        tmp_path, "#define API _Noreturn\n", "API void stop(void) { for (;;) {} }\n"
    )
    assert not CAnalyzer().analyze_file(path, tmp_path).index_symbols
    analyzer = CAnalyzer()
    analyzer.configure({"preinclude_headers": ["include/api.h"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert result.functions[0].signature == "API void stop(void)"


@pytest.mark.parametrize(
    "replacement", ["inline", "__inline", "__inline__", "_Noreturn", "[[noreturn]]"]
)
def test_function_specifier_aliases(tmp_path: Path, replacement: str) -> None:
    """Recover only function specifiers with unchanged declaration identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source directory.
    replacement : str
        Source-proven non-type function modifier.

    Returns
    -------
    None
        The original signature and callable name survive projection.
    """
    path = _fixture(
        tmp_path,
        "#define API " + replacement + "\n",
        '#include "api.h"\nAPI void stop(void) {}\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert result.functions[0].name == "stop"
    assert result.functions[0].signature == "API void stop(void)"


@pytest.mark.parametrize(
    "replacement",
    [
        "struct Nested { int member; } nested;",
        "const int constant;",
        "int array[4];",
        "int (*callback)(void);",
        "int member : 2;",
        "int member = callee();",
        "int member; int function(void);",
    ],
)
def test_unsupported_record_expansions_stay_partial(
    tmp_path: Path, replacement: str
) -> None:
    """Reject expansions that could hide emitted types, functions or expressions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source directory.
    replacement : str
        Replacement outside plain data-field normalization.

    Returns
    -------
    None
        The analyzer retains partial status instead of dropping supported evidence.
    """
    path = _fixture(
        tmp_path,
        "#define LAYOUT " + replacement + "\n",
        '#include "api.h"\nstruct Record { LAYOUT int written; };\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    assert not analyzer.analyze_file(path, tmp_path).index_symbols


@pytest.mark.parametrize(
    "header,source",
    [
        (
            "#define LAYOUT int hidden;\n",
            'struct R { LAYOUT int x; };\n#include "api.h"\n',
        ),
        (
            "#define LAYOUT int hidden;\n",
            '#include "api.h"\n#undef LAYOUT\nstruct R { LAYOUT int x; };\n',
        ),
        (
            "#define LAYOUT(x) int hidden;\n",
            '#include "api.h"\nstruct R { LAYOUT int x; };\n',
        ),
        (
            "#if FLAG\n#define LAYOUT int a;\n#else\n#define LAYOUT int b;\n#endif\n",
            '#include "api.h"\nstruct R { LAYOUT int x; };\n',
        ),
        (
            "#define BASE int\n#define LAYOUT BASE hidden;\n",
            '#include "api.h"\nstruct R { LAYOUT int x; };\n',
        ),
        ("#define LAYOUT int hidden;\n", '#include "api.h"\nLAYOUT int run(void) {}\n'),
        ("#define API int\n", '#include "api.h"\nAPI void run(void) {}\n'),
        (
            "#define API inline\n#define inline int\n",
            '#include "api.h"\nAPI void run(void) {}\n',
        ),
        (
            "#define LAYOUT int hidden;\n",
            '#include "api.h"\nstruct R { LAYOUT int broken( ; };\n',
        ),
    ],
)
def test_ambiguous_or_invalid_contexts_stay_partial(
    tmp_path: Path, header: str, source: str
) -> None:
    """Hold late definitions, overrides, undefined names and malformed bodies.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source directory.
    header : str
        Captured definitions with an invalidating or unsupported condition.
    source : str
        Source that cannot be safely recovered from that context.

    Returns
    -------
    None
        Partial status remains explicit.
    """
    path = _fixture(tmp_path, header, source)
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    assert not analyzer.analyze_file(path, tmp_path).index_symbols


@pytest.mark.parametrize("option", ["include_search_paths", "preinclude_headers"])
@pytest.mark.parametrize("value", ["include", [1], [""]])
def test_context_path_options_are_strict(option: str, value: object) -> None:
    """Reject malformed context options rather than guessing paths.

    Parameters
    ----------
    option : str
        Context option under validation.
    value : object
        Invalid option value.

    Returns
    -------
    None
        Configuration fails before any source access.
    """
    with pytest.raises(ValueError, match=option):
        CAnalyzer().configure({option: value})


@pytest.mark.parametrize("option", ["include_search_paths", "preinclude_headers"])
def test_context_paths_cannot_escape_root(tmp_path: Path, option: str) -> None:
    """Reject escaping configured paths before attempting header reads.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source boundary.
    option : str
        Configured source-input path option.

    Returns
    -------
    None
        Explicit escaping inputs fail before analysis.
    """
    path = _fixture(tmp_path, "", "int run(void) { return 0; }\n")
    analyzer = CAnalyzer()
    analyzer.configure({option: ["../outside"]})
    with pytest.raises(ValueError, match="inside the repository"):
        analyzer.analyze_file(path, tmp_path)


def test_context_header_change_invalidates_real_index(tmp_path: Path) -> None:
    """Rebuild unchanged source when captured context bytes change at fixed mtime.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Actual SQLite indexing boundary.

    Returns
    -------
    None
        Both files are reused unchanged and reindexed after header modification.
    """
    _fixture(
        tmp_path,
        "#define API __attribute__((cold))\n",
        "API int run(int x) { return x; }\n",
    )
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        'config_version=2\n[backend]\nname="sqlite"\n[embeddings]\nenabled=false\nsimilarity_index="exact"\n'
        '[plugins.analyzer-c]\npreinclude_headers=["include/api.h"]\n'
    )
    first = index_repo(tmp_path)
    assert first.failed == 0 and first.indexed == 2
    assert "run" in {s.name for s in symbol_inventory(tmp_path)}
    second = index_repo(tmp_path)
    assert second.indexed == 0 and second.reused == 2
    header = tmp_path / "include/api.h"
    before = header.stat()
    header.write_text("#define API __attribute__((hot))\n")
    os.utime(header, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = index_repo(tmp_path)
    assert changed.failed == 0 and changed.indexed == 2


def test_negative_lookup_and_context_order_invalidate_identity(tmp_path: Path) -> None:
    """Track failed lookups and ordered caller headers in reuse identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source and dependency boundary.

    Returns
    -------
    None
        New header availability and configuration changes require fresh analysis.
    """
    path = _fixture(
        tmp_path,
        "#define API inline\n",
        '#include "later.h"\nAPI int run(void) { return 0; }\n',
    )
    analyzer = CAnalyzer()
    analyzer.configure(
        {"include_search_paths": ["include"], "preinclude_headers": ["include/api.h"]}
    )
    identity = analyzer.analysis_input_fingerprint(path, tmp_path)
    assert analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    (tmp_path / "include/later.h").write_text("#define OTHER inline\n")
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    identity = analyzer.analysis_input_fingerprint(path, tmp_path)
    analyzer.configure(
        {
            "include_search_paths": ["include"],
            "preinclude_headers": ["include/api.h", "include/later.h"],
        }
    )
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    bad = json.loads(identity)
    bad["headers"][0][1] = "invalid"
    assert not analyzer.analysis_input_fingerprint_matches(
        path, tmp_path, json.dumps(bad)
    )


def test_context_reaches_all_conditional_signature_views(tmp_path: Path) -> None:
    """Rebase header availability correctly while retaining written alternatives.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source and header boundary.

    Returns
    -------
    None
        Both signatures and their shared body calls remain in original positions.
    """
    source = (
        '#include "api.h"\n#if MODE\nAPI int run(int x)\n#else\n'
        "API int run(long x)\n#endif\n{ return callee(x); }\n"
    )
    path = _fixture(tmp_path, "#define API inline\n", source)
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert {f.signature for f in result.functions} == {
        "API int run(int x)",
        "API int run(long x)",
    }
    assert all(
        f.calls[0].target == "callee" and f.calls[0].lineno == 7
        for f in result.functions
    )


def test_transitive_preinclude_identity_tracks_header_bytes(tmp_path: Path) -> None:
    """Capture nested context includes and invalidate their exact content changes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned input boundary.

    Returns
    -------
    None
        Cycles terminate and dependency mutation prevents stale reuse.
    """
    path = _fixture(
        tmp_path, '#include "defs.h"\n', "API int run(void) { return 0; }\n"
    )
    definitions = tmp_path / "include/defs.h"
    definitions.write_text('#include "api.h"\n#define API inline\n')
    analyzer = CAnalyzer()
    analyzer.configure({"preinclude_headers": ["include/api.h"]})
    assert analyzer.analyze_file(path, tmp_path).index_symbols
    identity = analyzer.analysis_input_fingerprint(path, tmp_path)
    payload = json.loads(identity)
    assert {item[0] for item in payload["headers"]} == {
        "include/api.h",
        "include/defs.h",
    }
    assert analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)
    stat = definitions.stat()
    definitions.write_text('#include "api.h"\n#define API __attribute__((cold))\n')
    os.utime(definitions, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert not analyzer.analysis_input_fingerprint_matches(path, tmp_path, identity)


def test_quoted_include_prefers_source_directory(tmp_path: Path) -> None:
    """Preserve quoted include precedence instead of merging unselected definitions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository boundary.

    Returns
    -------
    None
        Only the selected header licenses source recovery and enters the identity.
    """
    path = _fixture(
        tmp_path,
        "#define API int\n",
        '#include "api.h"\nAPI int run(void) { return 0; }\n',
    )
    (tmp_path / "api.h").write_text("#define API inline\n")
    analyzer = CAnalyzer()
    analyzer.configure({"include_search_paths": ["include"]})
    assert analyzer.analyze_file(path, tmp_path).index_symbols
    payload = json.loads(analyzer.analysis_input_fingerprint(path, tmp_path))
    assert [row[0] for row in payload["headers"]] == ["api.h"]


def test_missing_preinclude_fails_explicitly(tmp_path: Path) -> None:
    """Require an explicitly declared caller header to exist.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned source boundary.

    Returns
    -------
    None
        Missing configured context does not silently become default analysis.
    """
    path = _fixture(tmp_path, "", "int run(void) { return 0; }\n")
    analyzer = CAnalyzer()
    analyzer.configure({"preinclude_headers": ["absent.h"]})
    with pytest.raises(FileNotFoundError):
        analyzer.analysis_input_fingerprint(path, tmp_path)
