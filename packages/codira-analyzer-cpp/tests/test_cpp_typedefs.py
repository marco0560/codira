"""Verify C++ typedef identities at module and class scope.

Parameters
----------
None

Returns
-------
None
    Checks declarator names, source metadata and callable isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize(
    ("source", "names"),
    [
        ("typedef int Count;", ("Count",)),
        ("typedef int Count, *Pointer, Array[3];", ("Count", "Pointer", "Array")),
        ("typedef void (*Callback)(int parameter);", ("Callback",)),
        ("typedef int Function(int parameter);", ("Function",)),
        ("typedef int (&Reference)[3];", ("Reference",)),
        ("typedef int (*Handlers[2])(int parameter);", ("Handlers",)),
        ("typedef struct Tag {int field;} Alias, *Pointer;", ("Alias", "Pointer")),
        ("typedef struct {int field;} Anonymous;", ("Anonymous",)),
        ("typedef struct Node Node;", ("Node",)),
        ("namespace api {typedef int Count;}", ("api::Count",)),
        (
            "class Box {typedef int Private;public: typedef int Public;};",
            ("Box::Private", "Box::Public"),
        ),
        (
            "template<class T> struct Box {typedef typename T::type Value;};",
            ("Box::Value",),
        ),
        ("struct Box {typedef struct Inner {int field;} Alias;};", ("Box::Alias",)),
    ],
)
def test_cpp_typedef_names(tmp_path: Path, source: str, names: tuple[str, ...]) -> None:
    """Extract all alias declarators without parameter/type-name leakage.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.
    source : str
        Complete declaration forms.
    names : tuple[str, ...]
        Expected qualified typedef names.

    Returns
    -------
    None
        Verifies exact typedef names and absence of invented functions.
    """
    path = tmp_path / "types.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert {d.name for d in result.declarations if d.kind == "typedef"} == set(names)
    assert not result.functions
    assert not [m for cls in result.classes for m in cls.methods]


def test_cpp_typedef_preserves_records_and_callable_scope(tmp_path: Path) -> None:
    """Keep named records and member aliases while excluding function locals.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Checks the existing module-level artifact contract and lexical calls.
    """
    path = tmp_path / "types.cpp"
    path.write_text(
        "typedef struct Tag {int field;} Alias;\n"
        "struct Box {typedef int Value; int run(int value){typedef int Local;return helper(value);}};\n"
        "int run(int value){typedef void (*LocalCallback)(int);return helper(value);}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    identities = {(d.kind, d.name) for d in result.declarations}
    assert ("struct", "Tag") in identities
    assert ("typedef", "Alias") in identities
    assert ("typedef", "Box::Value") in identities
    assert not any("Local" in name for _, name in identities)
    assert [f.name for f in result.functions] == ["run"]
    assert [c.target for c in result.functions[0].calls] == ["helper"]
    assert [c.target for c in result.classes[0].methods[0].calls] == ["helper"]


def test_cpp_typedef_metadata_survives_namespace_projection(tmp_path: Path) -> None:
    """Preserve original signatures, lines and stable identities through recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated repository fixture.

    Returns
    -------
    None
        Checks source-bound metadata and separation from using aliases.
    """
    path = tmp_path / "types.cpp"
    path.write_bytes(
        b"#define BEGIN namespace api {\r\n#define END }\r\nBEGIN\r\n"
        + "// café\r\n".encode()
        + b"typedef int Count, *Pointer;\r\nusing Other = int;\r\nEND\r\n"
    )
    analyzer = CppAnalyzer()
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    typedefs = [d for d in result.declarations if d.kind == "typedef"]
    assert {d.name for d in typedefs} == {"api::Count", "api::Pointer"}
    assert all(
        d.lineno == 5 and d.signature == "typedef int Count, *Pointer;"
        for d in typedefs
    )
    assert len({d.stable_id for d in typedefs}) == 2
    assert any(
        d.kind == "type_alias" and d.name == "api::Other" for d in result.declarations
    )
    assert result == analyzer.analyze_file(path, tmp_path)
