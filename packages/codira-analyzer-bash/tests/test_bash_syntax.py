"""Positive, malformed and source-ownership controls for Bash recovery."""

from pathlib import Path

import pytest

from codira_analyzer_bash import BashAnalyzer, _new_parser
from codira_analyzer_bash.bash_syntax import bash_parse_root


@pytest.mark.parametrize(
    "source",
    [
        b'f(){ echo "${v:+${v};}x"; }\n',
        b'f(){ echo "${a[$left:$right]:-}"; }\n',
        b'f(){ echo "${a[${left}:${right}:$third]:-}"; }\n',
        b'f(){ echo "${v:$off:$len}"; }\n',
        b"f(){ [[ $v = -* && $mode != exec ]]; }\n",
        b'f(){ echo "$( ( cat ) <<< "$v" )"; }\n',
        b"f(){ X=-1 2>/dev/null || true; }\n",
        b"f(){ echo {{,us-}ascii,arabic}; }\n",
        b'f(){ case "$x" in *"foo (bar) "*" tail") echo ok;; esac; }\n',
        b'f(){ echo "${host#[}"; echo "${host%]}"; }\n',
        b'f(){ @prefix@tool "$@"; }\n',
        b'f(){ echo "${prefix:+ (p=$p)}"; }\n',
    ],
)
def test_bash_recovers_written_syntax(source: bytes) -> None:
    """Recover complete syntax while retaining root byte and line coordinates.

    Parameters
    ----------
    source : bytes
        Valid Bash source exposing a bundled grammar omission.

    Returns
    -------
    None
        The complete recovered root owns exactly the original source range.
    """
    original = _new_parser().parse(source).root_node
    recovered = bash_parse_root(_new_parser(), source)

    assert not recovered.has_error
    assert recovered.start_byte == original.start_byte
    assert recovered.end_byte == original.end_byte
    assert recovered.end_point == original.end_point


@pytest.mark.parametrize(
    "source",
    [
        b'f(){ echo "${v:+${v};}x";\n',
        b'f(){ echo "${a[$x:$y]"; }\n',
        b"f(){ [[ $x = -* && ]]; }\n",
        b"f(){ cat <<<; }\n",
        b"f(){ X=1 2>/dev/null ||; }\n",
        b'f(){ case x in *"literal"*|) :;; esac; }\n',
        b'f(){ if true; then echo "${v:+x;y}"; }\n',
        b"f(){ echo {{a,b}; ) }\n",
        b'f(){ echo "${host#[}"; for; }\n',
        b"f(){ @prefix@( ; }\n",
    ],
)
def test_bash_preserves_malformed_controls(source: bytes) -> None:
    """Keep independent syntax errors even beside recoverable word constructs.

    Parameters
    ----------
    source : bytes
        Malformed source checked separately by GNU Bash syntax-only probes.

    Returns
    -------
    None
        Recovery retains the original partial tree and bytes.
    """
    root = bash_parse_root(_new_parser(), source)

    assert root.has_error
    assert root.text == source


def test_bash_preserves_calls_and_original_signatures(tmp_path: Path) -> None:
    """Retain nested executable syntax while treating assignment names as data.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Original names, calls and declaration headers survive projection.
    """
    source = (
        "function f() {\n"
        " X=$(producer) 2>/dev/null || fallback\n"
        ' echo "${x:+$(inside); literal}"\n'
        ' [ -n "$x" ] && @prefix@tool "$x"\n'
        "}\n"
    )
    path = tmp_path / "script.sh"
    path.write_text(source)

    result = BashAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    function = result.functions[0]
    assert function.signature == "function f()"
    assert function.lineno == 1
    assert function.end_lineno == 5
    assert [(c.target, c.lineno) for c in function.calls] == [
        ("producer", 2),
        ("fallback", 2),
        ("echo", 3),
        ("inside", 3),
        ("[", 4),
        ("@prefix@tool", 4),
    ]
    assert path.read_text() == source


def test_bash_keeps_conditional_and_nested_definitions(tmp_path: Path) -> None:
    """Retain all written definitions with unique identities and lexical calls.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Conditional variants are not selected or overwritten by name.
    """
    path = tmp_path / "script.sh"
    path.write_text(
        "if true; then same(){ first; }; else same(){ second; }; fi\n"
        "outer(){ inner(){ nested; }; inner; }\n"
    )

    result = BashAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [f.name for f in result.functions] == ["same", "same", "outer", "inner"]
    assert len({f.stable_id for f in result.functions}) == 4
    assert [[c.target for c in f.calls] for f in result.functions] == [
        ["first"],
        ["second"],
        ["inner"],
        ["nested"],
    ]


def test_bash_clean_literals_are_not_projected() -> None:
    """Keep already clean literals, comments and quoted code opaque.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Clean input is returned without touching literal punctuation.
    """
    source = b"f(){ echo '${x:+a;b} <<< @foo@ {x,y}'; } # ${fake}\n"

    root = bash_parse_root(_new_parser(), source)

    assert not root.has_error
    assert root.text == source


def test_bash_heredoc_and_unset_calls_keep_literal_boundaries(tmp_path: Path) -> None:
    """Recover expanding heredoc calls while keeping escaped/quoted text literal.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Expanding substitutions and unset are calls; literal examples are not.
    """
    path = tmp_path / "script.sh"
    path.write_text(
        "usage(){\ncat <<EOF\n"
        "  $(last_name $0) --template '\\${PROJECT}-\\${YYYYMMDD}.src.tar.xz'\n"
        "  \\$(escaped)\nEOF\n"
        "unset VALUE\ncat <<'LITERAL'\n$(literal)\nLITERAL\n}\n"
    )

    result = BashAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [(c.target, c.lineno) for c in result.functions[0].calls] == [
        ("cat", 2),
        ("last_name", 3),
        ("unset", 6),
        ("cat", 7),
    ]
    assert result.functions[0].calls[2].external_target_kind == "Bash:<builtin>"


def test_bash_assignment_prefix_keeps_the_real_command(tmp_path: Path) -> None:
    """Keep assignment prefixes and quoted command words distinct from fake names.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source repository.

    Returns
    -------
    None
        Word recovery retains real command names and excludes assignment names.
    """
    path = tmp_path / "script.sh"
    path.write_text('f(){ X=1 run "${v:+a;b}"; "X=Y" "${v:+a;b}"; }\n')

    result = BashAnalyzer().analyze_file(path, tmp_path)

    assert result.index_symbols
    assert [c.target for c in result.functions[0].calls] == ["run", '"X=Y"']
