"""Public behavior for Rust module, local and associated declaration scopes."""

from pathlib import Path

from codira_analyzer_rust import RustAnalyzer


def test_rust_indexes_inline_modules_and_associated_items(tmp_path: Path) -> None:
    """Index module items with distinct identities and associated constants.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Repeated module-local names are independent native source occurrences.
    """
    path = tmp_path / "lib.rs"
    path.write_text(
        "mod external;\n"
        "mod left { use crate::One; pub struct S; fn run() {}\n"
        "impl S { const N: u8=1; fn go(&self){ helper(); } } }\n"
        "mod right { use crate::Two; pub struct S; fn run() {}\n"
        "impl S { const N: u8=2; fn go(&self){ other(); } } }\n"
    )

    result = RustAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [(f.name, f.lineno) for f in result.functions] == [("run", 2), ("run", 4)]
    assert len({f.stable_id for f in result.functions}) == 2
    assert len({c.stable_id for c in result.classes}) == 2
    assert [c.methods[0].calls[0].target for c in result.classes] == ["helper", "other"]
    assert all(c.methods[0].is_method for c in result.classes)
    constants = [d for d in result.declarations if d.kind == "constant"]
    assert [d.name for d in constants] == ["N", "N"]
    assert len({d.stable_id for d in constants}) == 2
    assert [i.name for i in result.imports] == ["crate::One", "crate::Two"]
    assert not (tmp_path / "external.rs").exists()


def test_rust_keeps_nested_callable_bodies_separate(tmp_path: Path) -> None:
    """Attach nested calls once while keeping closure calls in lexical owners.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Nested callable ownership, method flags and source calls remain distinct.
    """
    path = tmp_path / "lib.rs"
    path.write_text(
        "fn outer() {\n"
        " struct Local;\n"
        " impl Local { fn go(&self) {\n"
        "  fn inside(){ inner_call(); } inside();\n"
        " } }\n"
        " fn helper(){ nested_call(); }\n"
        " const N: u8={ const_call(); 1 };\n"
        " helper(); let _=||closure_call();\n"
        "}\n"
    )

    result = RustAnalyzer().analyze_file(path, tmp_path)

    outer, helper = result.functions
    assert [c.target for c in outer.calls] == ["helper", "closure_call"]
    assert [c.target for c in helper.calls] == ["nested_call"]
    methods = result.classes[0].methods
    assert [(m.name, m.is_method) for m in methods] == [("go", 1), ("inside", 0)]
    assert [[c.target for c in m.calls] for m in methods] == [
        ["inside"],
        ["inner_call"],
    ]
    assert {d.name for d in result.declarations} == {"Local", "N"}


def test_rust_deduplicates_owners_without_losing_repeated_names(tmp_path: Path) -> None:
    """Retain repeated block-local declarations and nested impl methods once.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        All written functions have unique identities and correct containers.
    """
    path = tmp_path / "lib.rs"
    path.write_text(
        "struct S; impl S { fn outer(&self) {\n"
        " {fn same(){a();}} {fn same(){b();}}\n"
        " struct T; impl T { fn inner(&self){c();} }\n"
        "} }\n"
        "macro_rules! ignored { () => { fn invented() {} }; }\n"
    )

    result = RustAnalyzer().analyze_file(path, tmp_path)

    assert [[m.name for m in c.methods] for c in result.classes] == [
        ["outer", "same", "same"],
        ["inner"],
    ]
    methods = [m for c in result.classes for m in c.methods]
    assert len({m.stable_id for m in methods}) == 4
    assert result.classes[0].methods[0].calls == ()
    assert result.classes[1].methods[0].is_method == 1
    assert not any(m.name == "invented" for m in methods)


def test_rust_enum_members_belong_to_their_own_enum(tmp_path: Path) -> None:
    """Keep enum discriminant-local declarations out of the outer member set.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Each member references its own stable enum identity.
    """
    path = tmp_path / "lib.rs"
    path.write_text("enum Outer { A = { enum Inner { X } 0 } }\n")

    result = RustAnalyzer().analyze_file(path, tmp_path)

    outer, inner = result.declarations
    assert [m.name for m in outer.enum_members] == ["A"]
    assert [m.name for m in inner.enum_members] == ["X"]
    assert outer.enum_members[0].parent_stable_id == outer.stable_id
    assert inner.enum_members[0].parent_stable_id == inner.stable_id
