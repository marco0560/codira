"""Behavioral and negative controls for coordinate-preserving Rust recovery."""

from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from tree_sitter import Parser

from codira_analyzer_rust import RustAnalyzer, _parser
from codira_analyzer_rust.rust_syntax import rust_parse_root


@pytest.mark.parametrize(
    "source",
    [
        b"macro_rules! m { (~ ~) => { ~~~ }; }",
        b"fn f(){m!(~ ~);}",
        b"fn f(){consume((a, #[cfg(test)] b));}",
        b"fn f(){consume((a, #[cfg(test)] /* gap */ #[allow(unused)] b));}",
        b'fn f(){consume((a, #[cfg_attr(test, doc="[cfg]#")] b));}',
        b"fn f(){let Foo {#[cfg(test)] a,b}=x;}",
        b"fn f(){match x {Foo{a,#[cfg(test)] b}=>{helper();}}}",
        b"type A=Box<dyn 'static+Send+Sync>;",
        b"fn f(x: Box<dyn 'a+Fn()>){helper();}",
        b"fn f(){helper::<-1>();}",
        b"fn f(){helper::<-0xff>();}",
        b"fn f(){let _=|x: i32,|{helper(x)};}",
        b"fn f(){let _=move |x: i32, /* gap */ |{helper(x)};}",
        b"fn f(){observe(|x: i32,|{helper(x)});}",
        b"fn f(){call::<Foo::<Bar>>();}",
        b"fn f(){call::<Foo::<Bar>,Baz::<Qux>>();}",
        b"fn f(){object.call::<module::Foo::<Bar>>();}",
    ],
)
def test_rust_recovers_supported_grammar_gaps(source: bytes) -> None:
    """Accept complete written constructs while retaining source coordinates.

    Parameters
    ----------
    source : bytes
        Valid syntax exposing one bundled grammar omission.

    Returns
    -------
    None
        Recovery is clean and preserves complete root coordinates.
    """
    original = _parser().parse(source).root_node
    recovered = rust_parse_root(_parser(), source)

    assert not recovered.has_error
    assert recovered.start_byte == original.start_byte
    assert recovered.end_byte == original.end_byte
    assert recovered.start_point == original.start_point
    assert recovered.end_point == original.end_point


@pytest.mark.parametrize(
    "source",
    [
        b"fn f(){~x;}",
        b"macro_rules! m {(~)=>{(};}",
        b"fn f(){consume((a,#[cfg(] b));}",
        b"fn f(){let _=(#[cfg(test)]);}",
        b"fn f(){let _=(a #[cfg(test)] + b);}",
        b"fn f(){helper::<--1>();}",
        b"fn f(){helper::<-)>();}",
        b"fn f(){helper::<dyn dyn 'static+Send>();}",
        b"fn f(){let _=|x,,|{};}",
        b"fn f(){foo(a | b, | c);}",
        b"fn f(){call::<Foo::<Bar> + @>();}",
        b"fn f(){consume((a, #[cfg(test)] b)); let =;}",
    ],
)
def test_rust_recovery_preserves_malformed_controls(source: bytes) -> None:
    """Reject malformed inputs even when another construct could be recovered.

    Parameters
    ----------
    source : bytes
        Invalid source or a valid recovery followed by an independent error.

    Returns
    -------
    None
        The original partial tree is returned without hiding its diagnostics.
    """
    original = _parser().parse(source).root_node
    recovered = rust_parse_root(_parser(), source)

    assert original.has_error
    assert recovered.has_error
    assert recovered.text == source


def test_rust_recovery_retains_original_artifacts(tmp_path: Path) -> None:
    """Retain signatures, punctuation, calls, docs and physical coordinates.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Public analysis reads artifacts from original rather than view bytes.
    """
    source = (
        "//! Crate documentation.\n"
        "macro_rules! m { (~) => { () }; }\n"
        "/// Public API.\n"
        "fn f(arg: Box<dyn 'static+Send>) {\n"
        '    let text = r###"#[cfg(fake)] ~ ::< |x,|"###;\n'
        "    consume((arg, #[cfg(test)] extra()));\n"
        "    helper::<-1>();\n"
        "    observe(|x: i32,| { callback(x); });\n"
        "    object.call::<Outer::<Inner>>();\n"
        "}\n"
    )
    path = tmp_path / "lib.rs"
    path.write_text(source)

    result = RustAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    function = result.functions[0]
    assert function.name == "f"
    assert function.lineno == 4
    assert function.end_lineno == 10
    assert function.signature == "fn f(arg: Box<dyn 'static+Send>)"
    assert function.parameters == ("arg",)
    assert result.declarations[0].signature == "macro_rules! m { (~) => { () }; }"
    assert [(c.target, c.lineno, c.col_offset) for c in function.calls] == [
        ("consume", 6, 4),
        ("extra", 6, 31),
        ("helper::<-1>", 7, 4),
        ("observe", 8, 4),
        ("callback", 8, 24),
        ("object.call::<Outer::<Inner>>", 9, 4),
    ]
    assert any("Public API." in item.text for item in result.documentation)
    assert path.read_text() == source


def test_rust_clean_source_keeps_original_tree() -> None:
    """Leave clean trees, literals and comments unchanged.

    Parameters
    ----------
    None

    Returns
    -------
    None
        An already clean source is never projected.
    """
    source = b'fn f(){let s=r#"~ #[cfg(fake)] ::< |x,|"#; /* ~ */ helper();}'

    root = rust_parse_root(_parser(), source)

    assert not root.has_error
    assert root.text == source


def test_rust_recovery_does_not_probe_unaffected_closures() -> None:
    """Keep closure recovery bounded when a different grammar gap is present.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Many valid closure arguments do not trigger repeated header probes.
    """
    source = (
        b"type A=Box<dyn 'static+Send>; fn f(){" + b"call(|x|x, |y|y);" * 100 + b"}"
    )
    parser = Mock(wraps=_parser())

    root = rust_parse_root(cast("Parser", parser), source)

    assert not root.has_error
    assert parser.parse.call_count < 5
