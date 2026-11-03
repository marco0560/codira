"""Verify C-owned guard recovery and declaration preservation.

Parameters
----------
None

Returns
-------
None
    Behavioral checks for syntax projections and source-owned API artifacts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from codira_analyzer_c import CAnalyzer, _new_parser
from codira_analyzer_c.c_preprocessing import _c_language_source, _parse_c_source

from codira.indexer import index_repo
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from pathlib import Path


_HEADER = b"""#ifndef API_H
#define API_H
#ifdef __cplusplus
extern "C" {
#endif
#if WINDOWS
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif
typedef int (*callback)(int value);
/// Apply a callback.
API
int apply(callback handler, int value);
int (*not_a_function)(void);
#ifdef __cplusplus
}
#endif
#endif
"""


def test_c_guard_recovery_preserves_api_spans_and_callback_types(
    tmp_path: Path,
) -> None:
    """Recover a C API without emitting pointer variables as callable symbols.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Original signature, coordinates, documentation and alias are retained.
    """
    path = tmp_path / "api.c"
    path.write_bytes(_HEADER)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [(f.name, f.lineno, f.end_lineno) for f in result.functions] == [
        ("apply", 13, None)
    ]
    function = result.functions[0]
    assert function.signature == "API int apply(callback handler, int value)"
    assert function.parameters == ("handler", "value")
    assert [(d.name, d.lineno) for d in result.declarations if d.kind == "typedef"] == [
        ("callback", 11)
    ]
    assert any(
        d.owner_stable_id == function.stable_id and "Apply a callback." in d.text
        for d in result.documentation
    )
    assert path.read_bytes() == _HEADER


@pytest.mark.parametrize(
    "guard",
    [b"ifdef __cplusplus", b"if defined(__cplusplus)", b"if defined __cplusplus"],
)
def test_c_language_guards_keep_c_alternative_and_report_unsupported_branch(
    tmp_path: Path, guard: bytes
) -> None:
    """Keep a parseable C alternative when C++-only branch syntax is unsupported.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.
    guard : bytes
        Exact C++-language condition.

    Returns
    -------
    None
        The C API survives at its written line and unsupported syntax is partial.
    """
    source = (
        b"#"
        + guard
        + b"\n#if OTHER\nnamespace cpp_only {\n#endif\n#else\nint c_api(void);\n#endif\n"
    )
    parsed = _parse_c_source(source, _new_parser())
    assert parsed.has_error
    assert _c_language_source(source, _new_parser().parse(source).root_node) == source
    path = tmp_path / "api.h"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [(function.name, function.lineno) for function in result.functions] == [
        ("c_api", 6)
    ]
    assert result.status is not None
    assert result.status.coverage_state.value == "partial"
    assert "cplusplus" in result.status.diagnostics[-1].message
    assert path.read_bytes() == source


@pytest.mark.parametrize("directive", [b"#define __cplusplus 1", b"#undef __cplusplus"])
def test_source_controlled_cplusplus_macro_keeps_source_conditions(
    directive: bytes,
) -> None:
    """Keep written language guards when source defines or undefines the macro.

    Parameters
    ----------
    directive : bytes
        Source-owned macro definition or invalidation.

    Returns
    -------
    None
        Parser projection changes only linkage syntax, not conditional content.
    """
    source = (
        directive
        + b'\n#ifdef __cplusplus\nextern "C" {\n#endif\nint api(void);\n#ifdef __cplusplus\n}\n#endif\n'
    )
    projected = _c_language_source(source, _new_parser().parse(source).root_node)
    assert b"#ifdef __cplusplus" in projected
    assert directive in projected
    assert b"int api(void);" in projected


@pytest.mark.parametrize(
    "source",
    [
        b"#define API __declspec(dllexport)\n#undef API\nAPI int api(void);\n",
        b"API int api(void);\n#define API __declspec(dllexport)\n",
        b"#define API(x) __declspec(x)\nAPI int api(void);\n",
        b"#if CHOICE\n#define API __declspec(dllexport)\n#else\n#define API int\n#endif\nAPI int api(void);\n",
        b"#define API __declspec(dllexport)\nAPI int api( {\n",
        b'#ifdef __cplusplus\nextern "C" {\nint api(void);\n',
    ],
)
def test_annotation_recovery_retains_unsafe_and_malformed_sources(
    source: bytes,
) -> None:
    """Require compatible source definitions and a wholly clean projected tree.

    Parameters
    ----------
    source : bytes
        Invalid, forward, function-like or conflicting annotation witness.

    Returns
    -------
    None
        Unsupported recovery never changes a partial source into a clean one.
    """
    original = _new_parser().parse(source).root_node
    assert original.has_error
    result = _parse_c_source(source, _new_parser())
    assert result.has_error and result.text == source


def test_comments_with_directive_text_remain_opaque(tmp_path: Path) -> None:
    """Keep fake C++ guards inside comments out of the directive stack.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        A real annotation is recovered without modifying comment text.
    """
    source = b"/*\n#ifdef __cplusplus\n#else\n#endif\n*/\n#define API __declspec(dllexport)\nAPI int api(void);\n"
    path = tmp_path / "api.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and [f.name for f in result.functions] == ["api"]
    tree = _parse_c_source(source, _new_parser())
    assert tree.text is not None and source[: source.index(b"*/") + 2] in tree.text


def test_conditional_definitions_and_typedef_alternatives_have_unique_ids(
    tmp_path: Path,
) -> None:
    """Retain lexical alternatives without importing locals into the module.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Both callback variants and definitions remain queryable and unique.
    """
    path = tmp_path / "variants.c"
    path.write_text(
        "#if MODE\ntypedef int (*callback)(int value);\nint run(int value) { return value; }\n#else\ntypedef int (*callback)(void);\nint run(void) { typedef int local_type; return 0; }\n#endif\nint run(int value);\n",
        encoding="utf-8",
    )
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 2
    assert len({f.stable_id for f in result.functions}) == 2
    aliases = [d for d in result.declarations if d.kind == "typedef"]
    assert [d.name for d in aliases] == ["callback", "callback"]
    assert len({d.stable_id for d in aliases}) == 2


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_recovered_c_api_indexes_through_real_backend(
    tmp_path: Path, backend_name: str
) -> None:
    """Publish recovered C prototypes and callback aliases through both backends.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    backend_name : str
        Real structural backend with embeddings disabled.

    Returns
    -------
    None
        Correct symbol kinds survive complete indexing and incremental reuse.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        f'[backend]\nname="{backend_name}"\n[embeddings]\nenabled=false\n',
        encoding="utf-8",
    )
    path = tmp_path / "api.c"
    path.write_bytes(_HEADER)
    report = index_repo(tmp_path)
    assert report.failed == 0 and report.indexed == 1
    backend = active_index_backend(root=tmp_path)
    assert backend.find_symbol(tmp_path, "apply") == [
        ("function", "api", "apply", str(path), 13)
    ]
    assert backend.find_symbol(tmp_path, "callback") == [
        ("typedef", "api", "callback", str(path), 11)
    ]
    assert backend.find_symbol(tmp_path, "not_a_function") == []
    reused = index_repo(tmp_path)
    assert reused.failed == 0 and reused.indexed == 0 and reused.reused == 1


@pytest.mark.parametrize("continuation", [b"", b"\\\n", b"\\\r\n"])
def test_empty_macro_cannot_create_a_preprocessor_directive(
    continuation: bytes,
) -> None:
    """Keep hash-prefixed invalid source from becoming an invented include.

    Parameters
    ----------
    continuation : bytes
        Optional physical-line splice before the hash token.

    Returns
    -------
    None
        Source-only macro replacement cannot change preprocessing directive status.
    """
    source = b"#define DROP\nDROP " + continuation + b"# include <stddef.h>\n"
    assert _parse_c_source(source, _new_parser()).has_error


def test_literal_hash_does_not_block_a_real_annotation() -> None:
    """Distinguish character/string hashes from preprocessing tokens.

    Parameters
    ----------
    None

    Returns
    -------
    None
        A real annotation remains recoverable beside a literal hash.
    """
    source = b"#define API __declspec(dllexport)\nAPI int run(void) { return '#'; }\n"
    assert not _parse_c_source(source, _new_parser()).has_error
