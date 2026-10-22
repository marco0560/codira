"""Friend functions retain namespace ownership and ordinary callable metadata.

Parameters
----------
None

Returns
-------
None
    Defines focused friend extraction regression tests.
"""

from __future__ import annotations

from pathlib import Path

from codira_analyzer_cpp import CppAnalyzer


def test_friend_function_definitions_and_chains_are_namespace_owned(
    tmp_path: Path,
) -> None:
    """Record friend definitions and merge their ordinary namespace prototypes.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Friends are free functions and their body calls remain available.
    """
    source = """namespace outer {
struct Box {
  friend int inspect(Box const& value);
  friend int inspect(Box const& value) { return consume(value); }
  friend class Access;
  struct Nested {
    friend void nested_friend() { nested_call(); }
  };
};
}
"""
    path = tmp_path / "friends.hpp"
    path.write_text(source, encoding="utf-8")

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    functions = {function.name: function for function in result.functions}
    assert set(functions) == {
        "outer::inspect",
        "outer::nested_friend",
    }
    inspect = functions["outer::inspect"]
    assert inspect.is_method == 0
    assert inspect.end_lineno == 4
    assert inspect.calls[0].target == "consume"
    nested = functions["outer::nested_friend"]
    assert nested.is_method == 0
    assert nested.calls[0].target == "nested_call"
    assert all(not cls.methods for cls in result.classes)


def test_friend_templates_overloads_and_abi_split_are_free_functions(
    tmp_path: Path,
) -> None:
    """Extract templated, overloaded and ABI-prefixed friend definitions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        Free-function identities remain distinct and no friend becomes a method.
    """
    source = """#define LLVM_ABI
struct Item {
  template<class T> friend T convert(T value) { return transform(value); }
  friend int compare(Item const&) { return 1; }
  friend bool compare(Item const&, Item const&) { return true; }
  LLVM_ABI friend bool operator==(Item const&, Item const&) { return true; }
  LLVM_ABI friend int abi_decl();
};
"""
    path = tmp_path / "friends.hpp"
    path.write_text(source, encoding="utf-8")

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    functions = {function.name: function for function in result.functions}
    assert set(functions) == {"convert", "compare", "operator==", "abi_decl"}
    assert functions["convert"].is_method == 0
    assert functions["convert"].calls[0].target == "transform"
    assert functions["operator=="].is_method == 0
    assert "friend" in functions["operator=="].signature
    compare = [item for item in result.functions if item.name == "compare"]
    assert len(compare) == 2
    assert len({item.stable_id for item in compare}) == 2
    assert len({item.stable_id for item in result.functions}) == 5
    assert functions["abi_decl"].is_method == 0
    assert all(not cls.methods for cls in result.classes)


def test_qualified_member_friend_remains_a_method(tmp_path: Path) -> None:
    """Keep qualified member friendship distinct from namespace friends.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        The existing member declaration is retained without adding a free call.
    """
    source = """class Owner { public: void run(); };
class Grant { friend void Owner::run(); friend class Other; };
"""
    path = tmp_path / "friends.hpp"
    path.write_text(source, encoding="utf-8")

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert not result.functions
    owner = next(item for item in result.classes if item.name == "Owner")
    assert [method.name for method in owner.methods] == ["run"]
    grant = next(item for item in result.classes if item.name == "Grant")
    assert not grant.methods


def test_global_friend_chain_coalesces_without_reclassifying_methods(
    tmp_path: Path,
) -> None:
    """Coalesce a global friend with its later definition and retain methods.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source directory.

    Returns
    -------
    None
        The friend is global while the ordinary member remains a method.
    """
    source = """struct GlobalBox {
  friend int inspect(GlobalBox const& value);
  int member() const;
};
int inspect(GlobalBox const& value) { return consume(value); }
"""
    path = tmp_path / "global-friends.hpp"
    path.write_text(source, encoding="utf-8")

    result = CppAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert len(result.functions) == 1
    inspect = result.functions[0]
    assert inspect.name == "inspect"
    assert inspect.is_method == 0
    assert inspect.lineno == 5
    assert inspect.end_lineno == 5
    assert inspect.calls[0].target == "consume"
    box = next(item for item in result.classes if item.name == "GlobalBox")
    assert [(method.name, method.is_method) for method in box.methods] == [
        ("member", 1)
    ]
