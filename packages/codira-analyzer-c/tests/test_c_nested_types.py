"""Verify source-owned C tags through record and declaration type bindings.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

from codira_analyzer_c import CAnalyzer


def test_nested_record_tags_preserve_names_lines_comments_and_enum_members(
    tmp_path: Path,
) -> None:
    """Retain nested tags and their own comments without inheriting owner comments.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    source = """/** Outer documentation. */
typedef struct Outer {
  /** Inner documentation. */
  struct Inner {
    union Value {
      enum Mode { OFF, ON } mode;
      int number;
    } value;
  } inner;
  struct Inner *reference;
  struct { struct Deep { int value; } child; } anonymous;
} Outer;
struct Global { int value; } instance;
void hidden(void) { struct Local { int value; } local; }
int (*callback)(struct Parameter { int value; } *);
"""
    path = tmp_path / "records.c"
    path.write_text(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    actual = {(item.kind, item.name): item for item in result.declarations}
    assert set(actual) == {
        ("typedef", "Outer"),
        ("struct", "Outer"),
        ("struct", "Inner"),
        ("union", "Value"),
        ("enum", "Mode"),
        ("struct", "Deep"),
        ("struct", "Global"),
    }
    for kind, name in actual:
        item = actual[kind, name]
        assert item.stable_id == f"c:{kind}:records.c:{name}"
        assert item.lineno == next(
            i
            for i, line in enumerate(source.splitlines(), 1)
            if (f"{kind} {name}" if kind != "typedef" else "typedef struct Outer")
            in line
        )
    assert actual["struct", "Outer"].docstring == "Outer documentation."
    assert actual["struct", "Inner"].docstring == "Inner documentation."
    assert actual["union", "Value"].docstring is None
    assert [item.name for item in actual["enum", "Mode"].enum_members] == ["OFF", "ON"]
    assert [item.name for item in result.functions] == ["hidden"]


def test_conditional_and_anonymous_record_members_keep_written_alternatives(
    tmp_path: Path,
) -> None:
    """Collect tags inside anonymous and conditional field containers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "alternatives.c"
    path.write_text("""struct {
#if FIRST
  struct First { int value; } first;
#else
  union Second { int value; } second;
#endif
} instance;
""")
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    tags = {
        (item.kind, item.name) for item in result.declarations if item.kind != "macro"
    }
    assert tags == {("struct", "First"), ("union", "Second")}


def test_nested_tag_enrichment_keeps_existing_forward_representative(
    tmp_path: Path,
) -> None:
    """Add missing tags without replacing an existing source-owned representative.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "existing.c"
    path.write_text("""/** Existing documentation. */
struct Shared;
struct Holder {
  struct Shared { int value; } shared;
  struct Added { int value; } added;
};
""")
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    tags = {item.name: item for item in result.declarations}
    assert tags["Shared"].lineno == 2
    assert tags["Shared"].signature == "struct Shared"
    assert tags["Shared"].docstring == "Existing documentation."
    assert tags["Added"].lineno == 5
