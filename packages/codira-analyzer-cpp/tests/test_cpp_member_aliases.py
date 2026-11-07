"""Verify member type aliases retain owning C++ record and namespace identity.

Parameters
----------
None

Returns
-------
None
"""

from pathlib import Path

from codira_analyzer_cpp import CppAnalyzer


def test_member_aliases_keep_owner_lines_comments_and_template_names(
    tmp_path: Path,
) -> None:
    """Extract only written member aliases without inventing method containers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    source = """namespace outer {
struct S {
  /** Value documentation. */
  using value_type = int;
private:
  using private_type = long;
public:
  template<class T> using rebind = T*;
  struct Inner { using type = double; };
};
union U { using type = int; int member; };
class C { using type = char; };
struct D : S { using S::value_type; };
void f() { using Local = int; }
}
"""
    path = tmp_path / "aliases.cpp"
    path.write_text(source)
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    aliases = {
        item.name: item for item in result.declarations if item.kind == "type_alias"
    }
    assert set(aliases) == {
        "outer::S::value_type",
        "outer::S::private_type",
        "outer::S::rebind",
        "outer::S::Inner::type",
        "outer::U::type",
        "outer::C::type",
    }
    for name, item in aliases.items():
        assert item.stable_id == f"cpp:type_alias:aliases.cpp:{name}"
        assert name.rsplit("::", 1)[1] in source.splitlines()[item.lineno - 1]
        assert item.signature.startswith("using ")
    assert aliases["outer::S::value_type"].docstring == "Value documentation."
    assert all(
        item.name not in {"outer::S", "outer::S::Inner", "outer::U", "outer::D"}
        for item in result.classes
    )
    assert [item.name for item in result.functions] == ["outer::f"]


def test_conditional_member_aliases_remain_distinct_by_owner(tmp_path: Path) -> None:
    """Collect aliases in all written conditional members with distinct owners.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
    """
    path = tmp_path / "conditional.cpp"
    path.write_text("""struct A {
#if FIRST
  using first = int;
#else
  using second = long;
#endif
};
struct B { using first = int; };
""")
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert {item.name for item in result.declarations if item.kind == "type_alias"} == {
        "A::first",
        "A::second",
        "B::first",
    }


def test_member_alias_does_not_invalidate_captured_external_method_owner(
    tmp_path: Path,
) -> None:
    """Keep header-proven method ownership when its class also has a member alias.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and captured header directory.

    Returns
    -------
    None
    """
    (tmp_path / "Owner.h").write_text("""namespace ns {
class Owner {
public:
  using type = int;
  void method();
};
}
""")
    path = tmp_path / "Owner.cpp"
    path.write_text('#include "Owner.h"\nvoid ns::Owner::method() {}\n')
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 1
    method = result.functions[0]
    assert method.is_method == 1
    assert method.owner_name == "ns::Owner"
    assert method.owner_stable_id == "cpp:class:Owner.h:ns::Owner"
    assert method.name == "method"


def test_namespace_alias_remains_conflicting_with_conditional_record_owner(
    tmp_path: Path,
) -> None:
    """Keep namespace alias evidence when a conditional record has the same name.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source and captured header directory.

    Returns
    -------
    None
    """
    (tmp_path / "Conflict.h").write_text("""#if FIRST
struct A { struct Type { void method(); }; };
#else
namespace A { using Type = int; }
#endif
""")
    path = tmp_path / "Conflict.cpp"
    path.write_text('#include "Conflict.h"\nvoid A::Type::method() {}\n')
    result = CppAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert len(result.functions) == 1
    assert result.functions[0].owner_name is None
    assert result.functions[0].owner_stable_id is None
    assert result.functions[0].is_method == 0
    assert result.functions[0].name == "A::Type::method"
