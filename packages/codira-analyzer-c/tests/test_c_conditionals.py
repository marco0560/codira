"""Verify complete conditional statements and written C signature alternatives.

Parameters
----------
None

Returns
-------
None
    Source preservation, unique identities and malformed-input controls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from codira_analyzer_c import CAnalyzer, _new_parser
from codira_analyzer_c.c_conditionals import c_parse_views
from codira_analyzer_c.c_preprocessing import _parse_c_source

if TYPE_CHECKING:
    from pathlib import Path


def test_shared_body_retains_signatures_coordinates_and_calls(tmp_path: Path) -> None:
    """Preserve both headers and the shared body without concatenating signatures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Both written parameter lists, source lines and identities survive.
    """
    source = b"#if WITH_LINE\nint handler(int value, int line)\n#else\nint handler(int value)\n#endif\n{ return helper(value); }\nint helper(int value) { return value; }\n"
    path = tmp_path / "shared.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    handlers = [f for f in result.functions if f.name == "handler"]
    assert [(f.lineno, f.end_lineno, f.parameters) for f in handlers] == [
        (2, 6, ("value", "line")),
        (4, 6, ("value",)),
    ]
    assert [f.signature for f in handlers] == [
        "int handler(int value, int line)",
        "int handler(int value)",
    ]
    assert len({f.stable_id for f in result.functions}) == 3
    assert all(
        [(c.target, c.lineno) for c in f.calls] == [("helper", 6)] for f in handlers
    )
    assert result.module.docstring is None and path.read_bytes() == source


def test_multiple_headers_have_linear_covering_views(tmp_path: Path) -> None:
    """Cover all independent choices without Cartesian growth.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Three two-way headers need four views and retain all six variants.
    """
    source = b"".join(
        f"#if MODE_{i}\nint f{i}(int value)\n#else\nint f{i}(void)\n#endif\n{{ return {i}; }}\n".encode()
        for i in range(3)
    )
    views = list(c_parse_views(source, _new_parser()))
    assert len(views) == 4 and all(not v.root.has_error for v in views)
    path = tmp_path / "linear.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and len(result.functions) == 6
    assert len({f.stable_id for f in result.functions}) == 6


def test_conditional_else_if_keeps_all_written_calls(tmp_path: Path) -> None:
    """Retain lexical calls from complete optional statement continuations.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        All branch calls keep their original physical source lines.
    """
    source = b"int run(int value) {\nif (value == 1) { first(); }\n#if EXTRA\nelse if (value == 2) { second(); }\n#endif\nelse { last(); }\nreturn value;\n}\n"
    path = tmp_path / "chain.c"
    path.write_bytes(source)
    assert _parse_c_source(source, _new_parser()).has_error
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols
    assert [(c.target, c.lineno) for c in result.functions[0].calls] == [
        ("first", 2),
        ("second", 4),
        ("last", 6),
    ]


@pytest.mark.parametrize(
    "source",
    [
        b"#if MODE\nint good(int value)\n#else\nint bad(\n#endif\n{ return 1; }\n",
        b"#if MODE\nint good(int value)\n#else\nint other(void)\n#else\nint bad(void)\n#endif\n{ return 1; }\n",
        b"#if MODE\nint good(int value)\n#else\nint other(void)\n{ return 1; }\n",
        b"int run(void) {\n#if (\nfirst();\n#endif\nreturn 0; }\n",
        b"int run(void) {\n#if MODE\nfirst();\n#else\nlast( ;\n#endif\nreturn 0; }\n",
        b"#if MODE\nint\n#else\nunsigned\n#endif\nrun(void) { return 0; }\n",
    ],
)
def test_invalid_views_and_incomplete_fragments_stay_partial(
    tmp_path: Path, source: bytes
) -> None:
    """Prevent a valid alternative or concatenated type from hiding an error.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.
    source : bytes
        Malformed directives, branch or unsupported split type.

    Returns
    -------
    None
        Partial input keeps its diagnostic status.
    """
    path = tmp_path / "bad.c"
    path.write_bytes(source)
    assert not CAnalyzer().analyze_file(path, tmp_path).index_symbols


def test_documentation_owners_follow_final_variant_ids(tmp_path: Path) -> None:
    """Remap branch documentation to final callable identities.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable repository.

    Returns
    -------
    None
        Variant docs have unique real owners and do not become module docs.
    """
    source = b"#if MODE\n/// First form.\nint run(int value)\n#else\n/// Second form.\nint run(void)\n#endif\n{ return 1; }\n"
    path = tmp_path / "docs.c"
    path.write_bytes(source)
    result = CAnalyzer().analyze_file(path, tmp_path)
    assert result.index_symbols and result.module.docstring is None
    ids = {f.stable_id for f in result.functions}
    assert len(ids) == 2
    docs = [d for d in result.documentation if d.owner_kind == "function"]
    assert len(docs) == 2 and {d.owner_stable_id for d in docs} == ids
    assert len({d.stable_id for d in docs}) == 2
