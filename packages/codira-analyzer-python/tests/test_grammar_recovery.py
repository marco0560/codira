"""Verify grammar recovery, original spans and malformed input boundaries.

Parameters
----------
None

Returns
-------
None
"""

from collections.abc import Callable, Iterator
from pathlib import Path
import tokenize

import pytest

from codira_analyzer_python.syntax import parse_python_artifacts, parse_python_source


@pytest.mark.parametrize(
    "source",
    [
        "def f[T: int = int, **P = int, *Ts = int](): pass\n",
        "class C[T = int]: pass\n",
        "type Alias[T = int] = list[T]\n",
        "def f(*args, **kwargs):\n return Union[*args, *(kwargs.values())]\n",
        "def f(x: a[:, :, c:d]): pass\n",
        "def f():\n (bar.\n baz)\n",
        "def f():\n (bar.\nbaz(\n ))\n",
    ],
)
def test_known_valid_forms_recover(source: str) -> None:
    """Accept native-verified grammar gaps without source execution.

    Parameters
    ----------
    source : str
        Valid Python input.

    Returns
    -------
    None
    """
    assert not parse_python_source(source).diagnostics


@pytest.mark.parametrize(
    "source",
    [
        "def f[T=](): pass\n",
        "def f[T=int=int](): pass\n",
        "def f[T=int:str](): pass\n",
        "def f[*Ts: int = int](): pass\n",
        "def f[**P: int = int](): pass\n",
        "def f[T=int, 2](): pass\n",
        "def f[*(T)](): pass\n",
        "def f():\n return X[*]\n",
        "def f(x: a[::, :+]): pass\n",
        "def f():\n (obj.\n )\n",
        "obj.\nmethod()\n",
    ],
)
def test_malformed_inputs_remain_partial(source: str) -> None:
    """Retain diagnostics for malformed lookalikes.

    Parameters
    ----------
    source : str
        Invalid Python input.

    Returns
    -------
    None
    """
    assert parse_python_source(source).diagnostics


def test_recovery_preserves_calls_headers_and_physical_coordinates(
    tmp_path: Path,
) -> None:
    """Preserve original bytes and positions across combined grammar views.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated logical root.

    Returns
    -------
    None
    """
    source = (
        "def f[T = int](x: a[:, :, c:d], *args, **kwargs):\r\n"
        "    (récepteur.\r\n"
        "méthode())\r\n"
        "    return X[*args, *(kwargs.values())]\r\n"
        "\r\n"
        "def after():\r\n"
        "    done()\r\n"
    )
    tree = parse_python_source(source)
    assert not tree.diagnostics
    result = parse_python_artifacts(tmp_path / "sample.py", tmp_path, source)
    first, after = result["functions"]
    assert (first["name"], first["lineno"], first["end_lineno"]) == ("f", 1, 4)
    assert first["parameters"] == ["x", "args", "kwargs"]
    assert first["signature"] == "f(x, *args, **kwargs)"
    assert [(c["target"], c["lineno"], c["col_offset"]) for c in first["calls"]] == [
        ("méthode", 3, 0),
        ("values", 4, 29),
    ]
    assert (after["lineno"], after["end_lineno"]) == (6, 7)
    assert after["calls"][0]["lineno"] == 7
    raw = source.encode()
    pending = [tree.root]
    while pending:
        node = pending.pop()
        assert 0 <= node.start_byte <= node.end_byte <= len(raw)
        assert node.start_line == raw[: node.start_byte].count(b"\n") + 1
        assert node.start_column == node.start_byte - (
            raw.rfind(b"\n", 0, node.start_byte) + 1
        )
        assert node.end_line == raw[: node.end_byte].count(b"\n") + 1
        assert node.end_column == node.end_byte - (
            raw.rfind(b"\n", 0, node.end_byte) + 1
        )
        pending.extend(node.children)


def test_default_features_use_original_target_and_offsets() -> None:
    """Expose default syntax as Python 3.13 at its original equals sign.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source = "def f[T: int = int](): pass\n"
    tree = parse_python_source(source)
    assert [
        (f.feature, f.minimum_version, f.line, f.column) for f in tree.target_features
    ] == [("type_parameter_default", "3.13", 1, 13)]


def test_literal_and_comment_text_does_not_drive_recovery() -> None:
    """Leave literal examples and comments outside transformation candidates.

    Parameters
    ----------
    None

    Returns
    -------
    None
    """
    source = 'text = "def f[T=int](): x[:, :]"\n# obj.\n\ndef broken(:\n'
    assert parse_python_source(source).diagnostics
    assert not parse_python_source(source).target_features


def test_definition_ends_exclude_trailing_comment_trivia(tmp_path: Path) -> None:
    """Keep class and function bounds on their last written syntax line.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Logical source root.

    Returns
    -------
    None
    """
    source = "class C:\n    def run(self):\n        if ok:\n            done()\n            # trailing inner comment\n        # trailing function comment\n    # trailing class comment\n"
    result = parse_python_artifacts(tmp_path / "sample.py", tmp_path, source)
    assert result["classes"][0]["end_lineno"] == 4
    assert result["classes"][0]["methods"][0]["end_lineno"] == 4


@pytest.mark.parametrize(
    ("source", "clean"),
    [("value = '''obj.\nmethod()'''\n", True), ("def f[T=int]():pass\n", False)],
)
def test_tokenizer_internal_failure_preserves_provider_result(
    monkeypatch: pytest.MonkeyPatch, source: str, clean: bool
) -> None:
    """Contain host tokenizer failures without guessing source validity.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Scoped host tokenizer fault injection.
    source : str
        Originally clean or partial provider input.
    clean : bool
        Expected original provider status.

    Returns
    -------
    None
    """

    def fail_tokens(readline: Callable[[], str]) -> Iterator[tokenize.TokenInfo]:
        """Model the observed CPython tokenizer internal failure.

        Parameters
        ----------
        readline : collections.abc.Callable[[], str]
            Source reader unused by the failing boundary.

        Returns
        -------
        collections.abc.Iterator[tokenize.TokenInfo]
            No tokens because the provider raises.

        Raises
        ------
        SystemError
            Always, reproducing the retained real-corpus failure.
        """
        raise SystemError("Negative size passed to PyUnicode_New")

    monkeypatch.setattr(
        "codira_analyzer_python.grammar_recovery.tokenize.generate_tokens", fail_tokens
    )
    assert (not parse_python_source(source).diagnostics) == clean


@pytest.mark.parametrize(
    ("target", "diagnostic_count"), [("==3.12.*", 1), ("==3.13.*", 0)]
)
def test_default_recovery_respects_declared_target(
    tmp_path: Path, target: str, diagnostic_count: int
) -> None:
    """Keep type-default target diagnostics independent of grammar recovery.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated source root.
    target : str
        Declared Python target range.
    diagnostic_count : int
        Expected target-version diagnostic count.

    Returns
    -------
    None
    """
    from codira_analyzer_python import PythonAnalyzer

    path = tmp_path / "sample.py"
    path.write_text("def f[T=int](): pass\n", encoding="utf-8")
    analyzer = PythonAnalyzer()
    analyzer.configure({"target_python": target})
    result = analyzer.analyze_file(path, tmp_path)
    assert result.index_symbols
    assert result.status is not None
    assert len(result.status.diagnostics) == diagnostic_count
    assert all(d.category == "target_version" for d in result.status.diagnostics)
