"""Architecture bulk-read, deep-graph and optional-rendering regressions.

Parameters
----------
None

Returns
-------
None
    Reports retain their mandatory evidence under large inventories and stalls.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest

import codira.architecture as ARCH
from codira.architecture_report import (
    ArchitectureRenderOptions,
    write_architecture_artifacts,
)
from codira.cli import main
from codira.indexer import index_repo
from codira.registry import active_index_backend

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codira.contracts import BackendQueryConnection, BackendQueryCursor


class CountingConnection:
    """Count bulk statements without depending on a concrete driver.

    Parameters
    ----------
    connection : BackendQueryConnection
        Wrapped caller-owned structural connection.

    Returns
    -------
    None
        Query count and close state expose accidental per-symbol work.
    """

    def __init__(self, connection: BackendQueryConnection) -> None:
        """Initialize counters around one real backend connection.

        Parameters
        ----------
        connection : BackendQueryConnection
            Underlying driver-independent connection.

        Returns
        -------
        None
            The underlying connection remains open.
        """
        self.connection = connection
        self.statements: list[str] = []
        self.closed = False

    def execute(
        self, statement: str, parameters: Sequence[object] = ()
    ) -> BackendQueryCursor:
        """Forward and count one statement.

        Parameters
        ----------
        statement : str
            Exact backend SQL.
        parameters : sequence of object, optional
            Bound query parameters.

        Returns
        -------
        BackendQueryCursor
            Real driver results.
        """
        self.statements.append(statement)
        return self.connection.execute(statement, parameters)

    def cursor(self) -> BackendQueryCursor:
        """Expose the underlying cursor interface.

        Parameters
        ----------
        None

        Returns
        -------
        BackendQueryCursor
            A real driver cursor.
        """
        return self.connection.cursor()

    def close(self) -> object:
        """Record explicit closure of the caller-owned connection.

        Parameters
        ----------
        None

        Returns
        -------
        object
            The underlying close result.
        """
        self.closed = True
        return self.connection.close()


@pytest.mark.parametrize("backend_name", ["sqlite", "duckdb"])
def test_bulk_architecture_preserves_legacy_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend_name: str
) -> None:
    """Keep graph semantics while sharing a session and avoiding metric queries.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source and index.
    monkeypatch : pytest.MonkeyPatch
        Instruments connection ownership and substitutes a legacy-only backend.
    backend_name : str
        First-party backend under test.

    Returns
    -------
    None
        Bulk and legacy facts agree; bulk reads execute exactly four statements.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text(
        f'[embeddings]\nenabled = false\n[backend]\nname = "{backend_name}"\n'
    )
    (tmp_path / "target.py").write_text("def target():\n    return 1\n")
    (tmp_path / "source.py").write_text(
        "from target import target\ndef caller():\n    callback = target\n    print(target())\n"
        + "\n".join(f"def item{i}():\n    return {i}\n" for i in range(150))
    )
    assert index_repo(tmp_path).failed == 0
    backend = active_index_backend(root=tmp_path)
    conn = CountingConnection(
        cast("BackendQueryConnection", backend.open_connection(tmp_path))
    )
    try:
        legacy_snapshot = ARCH._legacy_architecture_snapshot(backend, tmp_path, conn)
        expected = ARCH._architecture_model_from_snapshot(tmp_path, legacy_snapshot)
        conn.statements.clear()
        model = ARCH.build_architecture_model_from_index(tmp_path, conn=conn)
        assert model == expected
        assert len(conn.statements) == 4
        assert not any("COUNT(" in statement.upper() for statement in conn.statements)
        assert conn.closed is False
        assert {edge.kind for edge in model.dependencies} >= {
            "import",
            "call",
            "reference",
        }
        legacy = SimpleNamespace(
            symbol_inventory=backend.symbol_inventory,
            module_imports=backend.module_imports,
            find_call_edges=backend.find_call_edges,
            find_callable_refs=backend.find_callable_refs,
            open_connection=backend.open_connection,
            close_connection=backend.close_connection,
        )
        with monkeypatch.context() as scoped:
            scoped.setattr(ARCH, "active_index_backend", lambda **_kwargs: legacy)
            assert (
                ARCH.build_architecture_model_from_index(tmp_path, conn=conn)
                == expected
            )
            assert not conn.closed
    finally:
        conn.close()
    opened = Mock(wraps=backend.open_connection)
    closed = Mock(wraps=backend.close_connection)
    monkeypatch.setattr(backend, "open_connection", opened)
    monkeypatch.setattr(backend, "close_connection", closed)
    monkeypatch.setattr(ARCH, "active_index_backend", lambda **_kwargs: backend)
    assert ARCH.build_architecture_model_from_index(tmp_path) == expected
    assert opened.call_count == closed.call_count == 1


def test_deep_architecture_cycle_does_not_use_python_recursion() -> None:
    """Aggregate a cycle deeper than the interpreter's recursion limit.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Iterative strongly-connected traversal retains every member.
    """
    names = [f"m{i:04d}" for i in range(1500)]
    modules = tuple(
        ARCH.ArchitectureModule(name, name + ".py", "python", ()) for name in names
    )
    relations = tuple(
        ARCH.ArchitectureRelation(
            source,
            destination,
            "call",
            ARCH.ArchitectureSymbolEvidence(source, "call", source + ".py", 1),
        )
        for source, destination in zip(names, names[1:] + names[:1], strict=True)
    )
    model = ARCH.build_architecture_model(modules, relations)
    assert len(model.cycles) == 1
    assert model.cycles[0].members == tuple(names)


@pytest.mark.parametrize("timeout", [0.2, 0.3])
def test_svg_timeout_retains_mandatory_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, timeout: float
) -> None:
    """Reap a stalled owned renderer and preserve a complete report manifest.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable executable and report output.
    monkeypatch : pytest.MonkeyPatch
        Selects a dummy owned renderer rather than real Graphviz.
    timeout : float
        Bounded renderer deadline.

    Returns
    -------
    None
        Optional SVG failure leaves mandatory artifacts and timing provenance.
    """
    executable = tmp_path / "dummy-dot"
    executable.write_text(
        "#!" + sys.executable + "\n"
        "import json, os, pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "pathlib.Path(sys.argv[3] + '.pids').write_text(json.dumps([os.getpid(), child.pid]))\n"
        "pathlib.Path(sys.argv[3]).write_text('partial svg')\n"
        "time.sleep(60)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda _name: str(executable))
    model = ARCH.build_architecture_model((), ())
    policy = ARCH.analyze_architecture_policy(model, ARCH.ArchitecturePolicy((), ()))
    result = write_architecture_artifacts(
        model,
        policy,
        tmp_path / "report",
        options=ArchitectureRenderOptions(
            svg_timeout_seconds=timeout, phase_timings={"extraction_seconds": 0.5}
        ),
    )
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["svg"]["available"] is False
    assert "exceeded" in manifest["svg"]["warning"]
    assert manifest["timings"]["extraction_seconds"] == 0.5
    assert manifest["timings"]["svg_seconds"] >= timeout
    assert result.svg_path is None
    assert not (result.output_dir / "architecture.svg").exists()
    assert all((result.output_dir / name).exists() for name in manifest["artifacts"])
    for pid in json.loads((result.output_dir / "architecture.svg.pids").read_text()):
        process_state = Path(f"/proc/{pid}/stat")
        if process_state.exists():
            assert process_state.read_text().split(")", 1)[1].split()[0] == "Z"
    monkeypatch.setattr(
        shutil, "which", Mock(side_effect=AssertionError("unexpected renderer"))
    )
    skipped = write_architecture_artifacts(
        model,
        policy,
        tmp_path / "report",
        options=ArchitectureRenderOptions(render_svg=False),
    )
    assert skipped.warning and "disabled by operator" in skipped.warning


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf")])
def test_invalid_svg_bound_leaves_output_untouched(
    tmp_path: Path, timeout: float
) -> None:
    """Reject invalid renderer limits before publishing any report files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable output location.
    timeout : float
        Negative or nonfinite renderer bound.

    Returns
    -------
    None
        Invalid controls cannot launch an unbounded renderer accidentally.
    """
    model = ARCH.build_architecture_model((), ())
    policy = ARCH.analyze_architecture_policy(model, ARCH.ArchitecturePolicy((), ()))
    output = tmp_path / "report"
    with pytest.raises(ValueError, match="finite and nonnegative"):
        write_architecture_artifacts(
            model,
            policy,
            output,
            options=ArchitectureRenderOptions(svg_timeout_seconds=timeout),
        )
    assert not output.exists()


def test_cli_can_omit_svg_and_records_phase_timings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise public renderer controls through a real indexed CLI report.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source, index and report output.
    monkeypatch : pytest.MonkeyPatch
        Selects the source root and public CLI arguments.

    Returns
    -------
    None
        No SVG is requested and all four measured phases are recorded.
    """
    (tmp_path / ".codira").mkdir()
    (tmp_path / ".codira/config.toml").write_text("[embeddings]\nenabled = false\n")
    (tmp_path / "source.py").write_text("def answer():\n    return 42\n")
    index_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["codira", "arch", "--no-svg", "--svg-timeout-seconds", "0"]
    )
    assert main() == 0
    manifest = json.loads(
        (tmp_path / ".codira/architecture-report/manifest.json").read_text()
    )
    assert manifest["render_options"] == {"svg": False, "svg_timeout_seconds": 0}
    assert "disabled by operator" in manifest["svg"]["warning"]
    assert set(manifest["timings"]) == {
        "extraction_seconds",
        "policy_seconds",
        "artifacts_seconds",
        "svg_seconds",
    }
