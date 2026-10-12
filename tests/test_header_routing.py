"""Regressions for C/C++ header eligibility, precedence and indexed coverage.

Parameters
----------
None

Returns
-------
None
    Tests use owned repositories and both structural backends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from codira.contracts import LanguageAnalyzer

import pytest
from codira_analyzer_c import CAnalyzer
from codira_analyzer_cpp import CppAnalyzer

from codira.indexer import _select_language_analyzer, index_repo
from codira.query.exact import symbol_inventory


@pytest.mark.parametrize(
    ("source", "neighbours", "mode", "expected"),
    [
        ("int add(int x);\n", (), "auto", "c"),
        ("namespace demo { class Widget {}; }\n", (), "auto", "cpp"),
        ("template<class T> struct Box { T value; };\n", (), "auto", "cpp"),
        (
            '// namespace fake {}\nconst char *text = "class Fake {};";\n',
            (),
            "auto",
            "c",
        ),
        ("int add(int x);\n", (".cpp",), "auto", "cpp"),
        ("int add(int x);\n", (".c", ".cpp"), "auto", "c"),
        ("int add(int x);\n", (), "cpp", "cpp"),
        ("namespace demo {}\n", (), "c", "c"),
    ],
)
def test_header_selection_preserves_c_and_recovers_cpp(
    tmp_path: Path, source: str, neighbours: tuple[str, ...], mode: str, expected: str
) -> None:
    """Route mixed and header-only inputs independently of registration order.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository root.
    source : str
        Header syntax, including misleading comments or literals.
    neighbours : tuple of str
        Same-stem translation unit suffixes.
    mode : str
        Explicit or automatic header language setting.
    expected : str
        Required selected analyzer.

    Returns
    -------
    None
        Generic C claims cannot hide an eligible C++ header.
    """
    path = tmp_path / "sample.h"
    path.write_text(source)
    for suffix in neighbours:
        path.with_suffix(suffix).write_text("")
    c, cpp = CAnalyzer(), CppAnalyzer()
    cpp.configure({"header_language": mode})
    orders: tuple[list[LanguageAnalyzer], list[LanguageAnalyzer]] = ([c, cpp], [cpp, c])
    for analyzers in orders:
        assert _select_language_analyzer(path, analyzers, tmp_path).name == expected


def test_cpp_header_exclusions_and_invalid_override(tmp_path: Path) -> None:
    """Keep path exclusions authoritative and reject invalid language settings.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned header location.

    Returns
    -------
    None
        Opting out leaves the C analyzer eligible.
    """
    path = tmp_path / "sample.h"
    path.write_text("namespace demo {}\n")
    cpp = CppAnalyzer()
    cpp.configure({"exclude_paths": ["sample.h"]})
    assert _select_language_analyzer(path, [CAnalyzer(), cpp], tmp_path).name == "c"
    with pytest.raises(ValueError, match="header_language"):
        cpp.configure({"header_language": "invented"})


@pytest.mark.parametrize("backend", ["sqlite", "duckdb"])
def test_header_language_change_recovers_indexed_symbols(
    tmp_path: Path, backend: str
) -> None:
    """Reindex changed header language, retaining C and C++ symbols and docs.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Owned repository and index root.
    backend : str
        Structural backend under test.

    Returns
    -------
    None
        Header-only C++ declarations survive full and incremental indexing.
    """
    (tmp_path / ".codira.toml").write_text(
        f'config_version = 2\n[backend]\nname = "{backend}"\n'
        '[embeddings]\nenabled = false\nsimilarity_index = "exact"\n'
    )
    include = tmp_path / "include"
    include.mkdir()
    c_header = include / "c_api.h"
    c_header.write_text("int c_api(int value) { return value; }\n")
    cpp_header = include / "widget.h"
    cpp_header.write_text("int old_api(int value) { return value; }\n")
    first = index_repo(tmp_path, full=True)
    assert first.failed == 0
    cpp_header.write_text(
        "#ifndef WIDGET_H\n#define WIDGET_H\n#include <vector>\nnamespace demo {\n/** A documented C++ widget. */\n"
        "class Widget { public: /** Read the value. */ int value() const { return 1; } };\n}\n#endif\n"
    )
    second = index_repo(tmp_path)
    assert second.failed == 0
    names = {item.name for item in symbol_inventory(tmp_path)}
    assert "c_api" in names
    assert any("Widget" in name for name in names)
    assert "old_api" not in names
    analysis = CppAnalyzer().analyze_file(cpp_header, tmp_path)
    assert analysis.index_symbols
    assert analysis.documentation
    assert any(item.name == "vector" for item in analysis.imports)
    third = index_repo(tmp_path)
    assert third.indexed == 0
    assert third.reused == 2


def test_cpp_guarded_methods_and_branches_retain_scope(tmp_path: Path) -> None:
    """Traverse nested conditionals without treating local variables as exports.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Guarded header location.

    Returns
    -------
    None
        Guarded methods retain class ownership and both source branches appear.
    """
    path = tmp_path / "sample.h"
    path.write_text(
        "#ifndef SAMPLE_H\n#define SAMPLE_H\nnamespace demo {\n"
        "class Widget { public:\n#if FEATURE\n/** Read value. */\n"
        "int value() { int local = 1; return local; }\n#else\n"
        "int alternate() { return 2; }\n#endif\n};\n}\n#endif\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [item.name for item in result.classes] == ["demo::Widget"]
    assert {item.name for item in result.classes[0].methods} == {"value", "alternate"}
    assert all(item.is_method for item in result.classes[0].methods)
    assert all(item.name != "local" for item in result.declarations)
    assert result.documentation
