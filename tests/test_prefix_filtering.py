"""Tests for repo-root-relative prefix filtering across query surfaces.

Responsibilities
----------------
- Build multi-domain fixtures and assert prefix-aware symbol filtering across exact, semantic, and docstring channels.
- Ensure CLI prefix filtering, normalized prefixes, and ordered results stay deterministic.

Design principles
-----------------
Prefixes are tested with small fixtures to keep coverage deterministic and focused on filtering semantics.

Architectural role
------------------
This module belongs to the **query verification layer** guarding prefix constraints for retrieval surfaces.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from codira.cli import main
from codira.indexer import index_repo
from codira.prefix import normalize_prefix
from codira.query.context import context_for
from codira.query.exact import (
    docstring_issues,
    find_call_edges,
    find_callable_refs,
    find_symbol,
)
from codira.semantic.search import embedding_candidates
from codira.storage import init_db

if TYPE_CHECKING:
    from pathlib import Path


def _write_prefix_fixture(root: Path) -> None:
    """
    Write a multi-domain fixture used to test prefix filtering.

    Parameters
    ----------
    root : pathlib.Path
        Temporary repository root to populate.

    Returns
    -------
    None
        The fixture files are created under ``root``.
    """
    pkg = root / "pkg"
    other = root / "other"
    pkg.mkdir()
    other.mkdir()

    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (other / "__init__.py").write_text("", encoding="utf-8")

    (pkg / "b.py").write_text(
        '"""Prefix fixture helper module."""\n'
        "\n"
        "def imported_helper():\n"
        '    """Schema migration helper for pkg callers."""\n'
        "    return 1\n"
        "\n"
        "def shared_symbol():\n"
        '    """Schema migration symbol owned by pkg.b."""\n'
        "    return 2\n"
        "\n"
        "def undocumented_pkg():\n"
        "    return 3\n",
        encoding="utf-8",
    )

    (pkg / "a.py").write_text(
        '"""Prefix fixture caller module."""\n'
        "\n"
        "from pkg.b import imported_helper as external\n"
        "\n"
        "def caller():\n"
        '    """Call the pkg helper."""\n'
        "    external()\n"
        "    return 1\n"
        "\n"
        "def registry():\n"
        '    """Return a callable reference without invoking it."""\n'
        "    return external\n",
        encoding="utf-8",
    )

    (other / "c.py").write_text(
        '"""Independent fixture module outside pkg."""\n'
        "\n"
        "def shared_symbol():\n"
        '    """Schema migration symbol owned by other.c."""\n'
        "    return 4\n"
        "\n"
        "def undocumented_other():\n"
        "    return 5\n",
        encoding="utf-8",
    )


def test_find_symbol_respects_prefix(tmp_path: Path) -> None:
    """
    Restrict exact symbol lookup to files under one prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts exact symbol filtering by defining-file prefix.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    pkg_rows = find_symbol(tmp_path, "shared_symbol", prefix="pkg")
    other_rows = find_symbol(tmp_path, "shared_symbol", prefix="other")

    assert len(pkg_rows) == 1
    assert pkg_rows[0][1] == "pkg.b"
    assert len(other_rows) == 1
    assert other_rows[0][1] == "other.c"


def test_embedding_candidates_respect_prefix(tmp_path: Path) -> None:
    """
    Restrict embedding matches to files under the selected prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts embedding-channel filtering by file prefix.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    matches = embedding_candidates(
        tmp_path,
        "schema migration helper",
        limit=5,
        min_score=0.0,
        prefix="pkg/b.py",
    )

    assert matches
    assert all(symbol[3] == str(tmp_path / "pkg" / "b.py") for _, symbol in matches)


def test_call_and_ref_queries_filter_on_owner_prefix(tmp_path: Path) -> None:
    """
    Apply prefix filtering to caller-owned edges and references.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts owner-side prefix semantics for calls and refs.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    assert find_call_edges(
        tmp_path,
        "imported_helper",
        module="pkg.b",
        incoming=True,
        prefix="pkg/a.py",
    ) == [("pkg.a", "caller", "pkg.b", "imported_helper", 1)]
    assert (
        find_call_edges(
            tmp_path,
            "imported_helper",
            module="pkg.b",
            incoming=True,
            prefix="pkg/b.py",
        )
        == []
    )

    assert find_callable_refs(
        tmp_path,
        "imported_helper",
        module="pkg.b",
        incoming=True,
        prefix="pkg/a.py",
    ) == [("pkg.a", "registry", "pkg.b", "imported_helper", 1)]
    assert (
        find_callable_refs(
            tmp_path,
            "imported_helper",
            module="pkg.b",
            incoming=True,
            prefix="pkg/b.py",
        )
        == []
    )


def test_docstring_audit_respects_prefix(tmp_path: Path) -> None:
    """
    Restrict docstring issues to the selected defining-file prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts prefix-filtered audit messages.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    pkg_issues = docstring_issues(tmp_path, prefix="pkg")
    other_issues = docstring_issues(tmp_path, prefix="other")

    assert any(
        issue[1] == "Function undocumented_pkg: Missing docstring"
        for issue in pkg_issues
    )
    assert all("undocumented_other" not in issue[1] for issue in pkg_issues)
    assert any(
        issue[1] == "Function undocumented_other: Missing docstring"
        for issue in other_issues
    )
    assert all("undocumented_pkg" not in issue[1] for issue in other_issues)


def test_docstring_audit_skips_bash_module_missing_docstring_noise(
    tmp_path: Path,
) -> None:
    """
    Avoid docstring-audit noise for Bash entrypoint wrappers.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts shell wrappers do not emit docstring issues.
    """
    script_dir = tmp_path / "scripts"
    script_dir.mkdir()
    (script_dir / "build.sh").write_text(
        "build() {\n    echo hello\n}\n",
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    issues = docstring_issues(tmp_path)

    assert issues == []


def test_docstring_audit_skips_raises_requirement_for_pytest_tests(
    tmp_path: Path,
) -> None:
    """
    Avoid ``Raises`` noise for pytest-style tests with fallback assertions.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts pytest-style ``test_*`` functions do not require a
        ``Raises`` section when they contain local fallback raises.
    """
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        "def test_example():\n"
        '    """Exercise a local fallback assertion.\n'
        "\n"
        "    Parameters\n"
        "    ----------\n"
        "    None\n"
        "\n"
        "    Returns\n"
        "    -------\n"
        "    None\n"
        "        The test has no meaningful return value.\n"
        '    """\n'
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        '        message = "ignored"\n'
        "        assert message\n"
        "    else:\n"
        '        raise AssertionError("expected fallback")\n',
        encoding="utf-8",
    )

    init_db(tmp_path)
    index_repo(tmp_path)

    issues = docstring_issues(tmp_path)

    assert all(
        issue[1] != "Function test_example: Missing section: Raises" for issue in issues
    )


def test_context_for_respects_prefix_across_symbols_and_references(
    tmp_path: Path,
) -> None:
    """
    Restrict context retrieval, expansion, and references to one prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.

    Returns
    -------
    None
        The test asserts all returned files stay within the selected prefix.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    prefix = normalize_prefix(tmp_path, "pkg/b.py")
    assert prefix is not None

    payload = json.loads(
        context_for(
            tmp_path,
            "imported_helper",
            prefix="pkg/b.py",
            as_json=True,
        )
    )

    symbol_files = [
        row["file"] for row in payload["top_matches"] + payload["module_expansion"]
    ]
    assert symbol_files
    assert all(path == prefix for path in symbol_files)
    assert payload["references"] == []


def test_cli_prefix_is_applied_and_rejects_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Apply CLI prefix filtering and reject prefixes outside the repository.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts one successful scoped CLI run and one parser error.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "sym", "shared_symbol", "--prefix", "pkg"],
    )

    assert main() == 0
    captured = capsys.readouterr()
    assert "pkg.b.shared_symbol" in captured.out
    assert "other.c.shared_symbol" not in captured.out

    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "sym", "shared_symbol", "--prefix", "../escape"],
    )
    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2


def test_symbol_cli_json_includes_prefix_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Emit structured JSON for exact symbol lookup.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts the shared JSON envelope for `symbol`.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["codira", "sym", "shared_symbol", "--json", "--prefix", "pkg"],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "1.0"
    assert payload["command"] == "sym"
    assert payload["status"] == "ok"
    assert payload["query"] == {"name": "shared_symbol", "prefix": "pkg"}
    assert payload["results"] == [
        {
            "type": "function",
            "module": "pkg.b",
            "name": "shared_symbol",
            "file": str(tmp_path / "pkg" / "b.py"),
            "lineno": 7,
        }
    ]


def test_calls_and_refs_cli_json_emit_structured_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Emit structured JSON for graph-relation subcommands.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts structured owner-side filtering for calls and refs.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "imported_helper",
            "--module",
            "pkg.b",
            "--incoming",
            "--json",
            "--prefix",
            "pkg/a.py",
        ],
    )

    assert main() == 0
    calls_payload = json.loads(capsys.readouterr().out)
    assert calls_payload["command"] == "calls"
    assert calls_payload["status"] == "ok"
    assert calls_payload["query"] == {
        "name": "imported_helper",
        "module": "pkg.b",
        "incoming": True,
        "prefix": "pkg/a.py",
    }
    assert calls_payload["results"] == [
        {
            "caller_module": "pkg.a",
            "caller_name": "caller",
            "callee_module": "pkg.b",
            "callee_name": "imported_helper",
            "resolved": True,
        }
    ]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "imported_helper",
            "--module",
            "pkg.b",
            "--incoming",
            "--json",
            "--prefix",
            "pkg/a.py",
        ],
    )

    assert main() == 0
    refs_payload = json.loads(capsys.readouterr().out)
    assert refs_payload["command"] == "refs"
    assert refs_payload["status"] == "ok"
    assert refs_payload["query"] == {
        "name": "imported_helper",
        "module": "pkg.b",
        "incoming": True,
        "prefix": "pkg/a.py",
    }
    assert refs_payload["results"] == [
        {
            "owner_module": "pkg.a",
            "owner_name": "registry",
            "target_module": "pkg.b",
            "target_name": "imported_helper",
            "resolved": True,
        }
    ]


def test_calls_cli_tree_json_respects_prefix_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Keep bounded call-tree traversal constrained by the caller-side prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts tree-mode `calls` keeps the prefix in both query
        echoing and filtered traversal results.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "calls",
            "imported_helper",
            "--module",
            "pkg.b",
            "--incoming",
            "--tree",
            "--json",
            "--prefix",
            "pkg/a.py",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["query"] == {
        "name": "imported_helper",
        "module": "pkg.b",
        "incoming": True,
        "tree": True,
        "max_depth": 2,
        "max_nodes": 20,
        "prefix": "pkg/a.py",
    }
    assert payload["results"] == [
        {
            "module": "pkg.b",
            "name": "imported_helper",
            "display": "pkg.b.imported_helper",
            "resolved": True,
            "incoming": True,
            "cycle": False,
            "children": [
                {
                    "module": "pkg.a",
                    "name": "caller",
                    "display": "pkg.a.caller",
                    "resolved": True,
                    "cycle": False,
                    "children": [],
                }
            ],
        }
    ]


def test_refs_cli_tree_json_respects_prefix_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Keep bounded ref-tree traversal constrained by the owner-side prefix.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts tree-mode `refs` keeps the prefix in both query
        echoing and filtered traversal results.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "refs",
            "imported_helper",
            "--module",
            "pkg.b",
            "--incoming",
            "--tree",
            "--json",
            "--prefix",
            "pkg/a.py",
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["query"] == {
        "name": "imported_helper",
        "module": "pkg.b",
        "incoming": True,
        "tree": True,
        "max_depth": 2,
        "max_nodes": 20,
        "prefix": "pkg/a.py",
    }
    assert payload["results"] == [
        {
            "module": "pkg.b",
            "name": "imported_helper",
            "display": "pkg.b.imported_helper",
            "resolved": True,
            "incoming": True,
            "cycle": False,
            "children": [
                {
                    "module": "pkg.a",
                    "name": "registry",
                    "display": "pkg.a.registry",
                    "resolved": True,
                    "cycle": False,
                    "children": [],
                }
            ],
        }
    ]


def test_embeddings_and_audit_cli_json_emit_shared_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Emit structured JSON for embeddings and docstring auditing.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts command-specific metadata and filtered results.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "emb",
            "schema migration helper",
            "--json",
            "--limit",
            "3",
            "--prefix",
            "pkg/b.py",
        ],
    )

    assert main() == 0
    embeddings_payload = json.loads(capsys.readouterr().out)
    assert embeddings_payload["command"] == "emb"
    assert embeddings_payload["status"] == "ok"
    assert embeddings_payload["query"] == {
        "text": "schema migration helper",
        "limit": 3,
        "prefix": "pkg/b.py",
    }
    assert embeddings_payload["backend"]["name"]
    assert embeddings_payload["inventory"]
    assert embeddings_payload["results"]
    assert all(
        row["file"] == str(tmp_path / "pkg" / "b.py")
        for row in embeddings_payload["results"]
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "audit",
            "--json",
            "--prefix",
            "pkg",
        ],
    )

    assert main() == 0
    audit_payload = json.loads(capsys.readouterr().out)
    assert audit_payload["command"] == "audit"
    assert audit_payload["status"] == "ok"
    assert audit_payload["query"] == {"prefix": "pkg"}
    messages = {row["message"] for row in audit_payload["results"]}
    assert "Function undocumented_pkg: Missing docstring" in messages
    assert all("undocumented_other" not in message for message in messages)
    undocumented_pkg = next(
        row for row in audit_payload["results"] if row["name"] == "undocumented_pkg"
    )
    assert undocumented_pkg["stable_id"] == "python:function:pkg.b:undocumented_pkg"
    assert undocumented_pkg["symbol_type"] == "function"
    assert undocumented_pkg["module"] == "pkg.b"
    assert undocumented_pkg["file"] == str(tmp_path / "pkg" / "b.py")
    assert undocumented_pkg["lineno"] == 11
    assert undocumented_pkg["end_lineno"] == 12


def test_plain_docstring_audit_reports_file_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Include defining file locations in plain docstring-audit output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts plain audit output includes actionable file context.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "audit",
            "--prefix",
            "pkg",
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out
    assert (
        f"missing: Function undocumented_pkg: Missing docstring "
        f"[{tmp_path / 'pkg' / 'b.py'}:11]"
    ) in output


def test_json_cli_reports_no_matches_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Preserve empty-result semantics in JSON mode.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary directory provided by pytest.
    monkeypatch : pytest.MonkeyPatch
        Fixture used to control process state.
    capsys : pytest.CaptureFixture[str]
        Fixture used to capture CLI output.

    Returns
    -------
    None
        The test asserts no-match status and exit code for exact queries.
    """
    _write_prefix_fixture(tmp_path)
    init_db(tmp_path)
    index_repo(tmp_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "codira",
            "sym",
            "shared_symbol",
            "--json",
            "--prefix",
            "missing",
        ],
    )

    assert main() == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "sym"
    assert payload["status"] == "no_matches"
    assert payload["results"] == []
