"""Verify coherent metadata for logical C++ record redeclaration chains.

Parameters
----------
None

Returns
-------
None
    Defines source-level range, documentation, ownership and identity checks.
"""

from pathlib import Path

import pytest

from codira_analyzer_cpp import CppAnalyzer


@pytest.mark.parametrize("kind", ["class", "struct", "union"])
@pytest.mark.parametrize("forward_after", [False, True])
def test_definition_metadata_replaces_forward_record_range(
    tmp_path: Path, kind: str, forward_after: bool
) -> None:
    """Represent the full definition once despite surrounding declarations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    kind : str
        C++ record keyword.
    forward_after : bool
        Whether a later declaration follows the complete definition.

    Returns
    -------
    None
        Record and method identities survive with coherent definition metadata.
    """
    source = (
        "namespace demo {\n"
        "// Forward documentation.\n"
        f"{kind} Item;\n"
        "// Definition documentation.\n"
        f"{kind} Item {{\n"
        "public:\n"
        "  int run() { return 1; }\n"
        "};\n" + (f"{kind} Item;\n" if forward_after else "") + "}\n"
    )
    path = tmp_path / "records.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert len(result.classes) == 1
    record = result.classes[0]
    assert (record.name, record.lineno, record.end_lineno) == ("demo::Item", 5, 8)
    assert record.docstring == "Definition documentation."
    assert record.stable_id == "cpp:class:records.cpp:demo::Item"
    assert [method.name for method in record.methods] == ["run"]
    assert record.methods[0].lineno == 7
    if kind != "class":
        declaration = next(d for d in result.declarations if d.kind == kind)
        assert (declaration.name, declaration.lineno) == ("demo::Item", 5)
        assert declaration.signature == (
            f"{kind} Item {{ public: int run() {{ return 1; }} }}"
        )
        assert declaration.docstring == "Definition documentation."


@pytest.mark.parametrize("kind", ["class", "struct", "union"])
def test_forward_only_records_keep_one_coherent_first_declaration(
    tmp_path: Path, kind: str
) -> None:
    """Keep one semantic identity when no complete definition exists.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    kind : str
        C++ record keyword.

    Returns
    -------
    None
        Repeated declarations preserve the first declaration's range and comment.
    """
    path = tmp_path / "forward.cpp"
    path.write_text(
        f"// First documentation.\n{kind} Item;\n\n"
        f"// Later documentation.\n{kind} Item;\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    record = (
        result.classes[0]
        if kind == "class"
        else next(d for d in result.declarations if d.kind == kind)
    )
    assert (record.name, record.lineno) == ("Item", 2)
    if kind == "class":
        assert result.classes[0].end_lineno == 2
    else:
        declaration = next(d for d in result.declarations if d.kind == kind)
        assert declaration.signature == f"{kind} Item"
    assert record.docstring == "First documentation."


def test_out_of_line_nested_definition_keeps_namespace_owners_distinct(
    tmp_path: Path,
) -> None:
    """Merge a qualified nested definition without merging namespace homonyms.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Each logical record owns its definition's range and methods.
    """
    path = tmp_path / "nested.cpp"
    path.write_text(
        "namespace first {\n"
        "class Outer { public: class Inner; };\n"
        "class Outer::Inner {\n"
        "public: int run() { return 1; }\n"
        "};\n"
        "}\n"
        "namespace second {\n"
        "class Inner;\n"
        "class Inner { public: int other() { return 2; } };\n"
        "}\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    records = {c.name: c for c in result.classes}
    nested = records["first::Outer::Inner"]
    other = records["second::Inner"]
    assert (nested.lineno, nested.end_lineno) == (3, 5)
    assert (other.lineno, other.end_lineno) == (9, 9)
    assert [m.name for m in nested.methods] == ["run"]
    assert [m.name for m in other.methods] == ["other"]
    assert nested.stable_id != other.stable_id


@pytest.mark.parametrize("kind", ["class", "struct"])
def test_template_definition_owns_metadata_after_forward_declaration(
    tmp_path: Path, kind: str
) -> None:
    """Prefer the complete primary template while preserving logical identity.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    kind : str
        Template record keyword.

    Returns
    -------
    None
        The template's method container uses the complete record range.
    """
    path = tmp_path / "template.cpp"
    path.write_text(
        f"template<class T> {kind} Box;\n"
        f"template<class T> {kind} Box {{\n"
        "public: T get() { return T(); }\n"
        "};\n"
        f"template<class T> {kind} Box;\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert len(result.classes) == 1
    record = result.classes[0]
    assert (record.name, record.lineno, record.end_lineno) == ("Box", 2, 4)
    assert [m.name for m in record.methods] == ["get"]


def test_source_shifts_preserve_record_and_method_semantic_ids(tmp_path: Path) -> None:
    """Keep identities independent of offsets while updating definition ranges.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Source movement changes ranges without changing record or method IDs.
    """
    path = tmp_path / "shift.cpp"
    source = "class Item;\nclass Item { public: void run() {} };\n"
    path.write_text(source)
    before = CppAnalyzer().analyze_file(path, tmp_path)
    path.write_text("// Source movement.\n\n" + source + "class Item;\n")
    after = CppAnalyzer().analyze_file(path, tmp_path)
    assert before.index_symbols and after.index_symbols
    first, second = before.classes[0], after.classes[0]
    assert (first.lineno, first.end_lineno) == (2, 2)
    assert (second.lineno, second.end_lineno) == (4, 4)
    assert first.stable_id == second.stable_id
    assert first.methods[0].stable_id == second.methods[0].stable_id


@pytest.mark.parametrize("kind", ["struct", "union"])
def test_data_only_definition_signature_survives_later_forward_declaration(
    tmp_path: Path, kind: str
) -> None:
    """Keep a data-only record body without inventing a method container.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    kind : str
        Data-only record keyword.

    Returns
    -------
    None
        The declaration keeps the full written body and one stable identity.
    """
    path = tmp_path / "data.cpp"
    path.write_text(f"{kind} Data;\n{kind} Data {{ int value; }};\n{kind} Data;\n")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    assert result.classes == ()
    assert len(result.declarations) == 1
    record = result.declarations[0]
    assert (record.name, record.lineno, record.signature) == (
        "Data",
        2,
        f"{kind} Data {{ int value; }}",
    )


def test_opaque_enum_redeclaration_preserves_definition_members(tmp_path: Path) -> None:
    """Keep enum values when an opaque declaration follows the definition.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.

    Returns
    -------
    None
        Source members retain their ordered identities and complete signature.
    """
    path = tmp_path / "enum.cpp"
    path.write_text(
        "enum class Mode : int;\n"
        "enum class Mode : int { First = 1, Second };\n"
        "enum class Mode : int;\n"
    )
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.status is None
    record = next(d for d in result.declarations if d.kind == "enum")
    assert record.lineno == 2
    assert record.signature == "enum class Mode : int { First = 1, Second }"
    assert [m.name for m in record.enum_members] == ["First", "Second"]
    assert all(m.parent_stable_id == record.stable_id for m in record.enum_members)
