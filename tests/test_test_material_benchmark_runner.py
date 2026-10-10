"""Offline regressions for local runner outcome classification and checkpoints."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO
from unittest.mock import Mock

import pytest

from scripts import run_test_material_benchmarks as RUNNER


@pytest.mark.parametrize(
    ("argv", "stdout", "stderr", "code", "status"),
    [
        (
            ["codira", "refs", "name", "--json"],
            '{"status":"no_matches","results":[]}',
            "",
            1,
            "empty",
        ),
        (
            ["codira", "calls", "name", "--tree", "--dot"],
            "No call edges found for caller: name\n",
            "",
            1,
            "empty",
        ),
        (
            ["codira", "refs", "name", "--json"],
            '{"status":"no_matches"}',
            "",
            2,
            "failed",
        ),
        (["codira", "sym", "name", "--json"], "broken JSON", "", 0, "failed"),
        (
            ["codira", "index", "--json"],
            '{"summary":{"failed":2},"failures":[{"reason":"duplicate stable_id"}],"index_coverage":{"usable":true,"partial":true,"complete":false}}',
            "",
            0,
            "partial",
        ),
        (["codira", "index", "--json"], '{"summary":{"failed":0}}', "", 0, "passed"),
        (["codira", "index", "--json"], '{"status":"ok"}', "", 0, "failed"),
        (
            ["codira", "ctx", "name", "--json"],
            '{"status":"ok","results":[]}',
            "[codira] Index stale — rebuilding...\n",
            0,
            "invalid_measurement",
        ),
        (["codira", "ctx", "name", "--json"], '{"status":"error"}', "", 0, "failed"),
    ],
)
def test_outcomes(
    argv: list[str], stdout: str, stderr: str, code: int, status: str
) -> None:
    """Distinguish legitimate absence, partial analysis and execution errors.

    Parameters
    ----------
    argv : list of str
        Recorded invocation shape.
    stdout, stderr : str
        Representative retained outputs.
    code : int
        Process exit status.
    status : str
        Required classification.

    Returns
    -------
    None
        Assertions reject incorrect promotion or failure labeling.
    """
    result = RUNNER.classify_sample(argv, stdout, stderr, code)
    assert result["status"] == status
    assert result["timing_valid"] == (status in {"passed", "empty"})


def test_empty_checkpoint_resumes_without_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reuse an empty-result checkpoint and retain every measured invocation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable test workspace.
    monkeypatch : pytest.MonkeyPatch
        Replaces process execution with retained-output simulation.

    Returns
    -------
    None
        No Codira index or benchmark process is launched.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False)
    invocations = []

    def simulate(
        argv: list[str],
        *,
        env: dict[str, str],
        stdout: TextIO,
        stderr: TextIO,
        **options: object,
    ) -> SimpleNamespace:
        """Simulate a no-match CLI result without launching a child process.

        Parameters
        ----------
        argv : list of str
            Captured command.
        env : dict
            Child environment.
        stdout, stderr : object
            Open output streams.
        **options : object
            Process session and text mode options.

        Returns
        -------
        types.SimpleNamespace
            Exit status of the simulated process.
        """
        invocations.append(argv)
        stdout.write('{"status":"no_matches","results":[]}\n')
        return SimpleNamespace(returncode=1, wait=Mock(return_value=1))

    monkeypatch.setattr(subprocess, "Popen", simulate)
    argv = ["codira", "refs", "name", "--json"]
    first = campaign.command("refs", argv, repeats=3)
    second = campaign.command("refs", argv, repeats=3)
    assert first == second
    assert first["status"] == "empty"
    assert len(invocations) == 3
    assert len(first["samples"]) == 3
    assert all(Path(sample["stdout"]).is_file() for sample in first["samples"])


@pytest.mark.parametrize("extended", [False, True])
def test_unusable_partial_index_withholds_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extended: bool
) -> None:
    """Block reads and embedding work when a full index silently skips files.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable stage workspace.
    monkeypatch : pytest.MonkeyPatch
        Replaces every command with an outcome simulation.
    extended : bool
        Select the structural suite or local stress suite.

    Returns
    -------
    None
        Both suite variants exclude dependent queries without running Codira.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "temporary_root": str(tmp_path),
                "extended": extended,
                "profiles": [{"id": "primary"}],
            }
        )
    )
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False)
    invoked = []

    def simulate(key: str, argv: list[str], *, repeats: int = 1) -> dict[str, Any]:
        """Simulate a partially successful index and successful prerequisites.

        Parameters
        ----------
        key : str
            Stage identity.
        argv : list of str
            Captured CLI command.
        repeats : int, optional
            Requested measurement count.

        Returns
        -------
        dict
            Recorded status consumed by repository orchestration.
        """
        invoked.append(argv)
        result = {"key": key, "status": "partial" if "/index-full" in key else "passed"}
        campaign.results.append(result)
        return result

    monkeypatch.setattr(campaign, "command", simulate)
    repo = {
        "label": "fixture",
        "path": str(tmp_path),
        "configs": {"primary": "config.toml"},
        "repetitions": 3,
    }
    member = campaign.repository(repo, {"id": "primary", "embeddings": True})
    assert member is None
    assert not any(
        argv[1] in RUNNER.READ_COMMANDS or "--embeddings-only" in argv
        for argv in invoked
    )
    assert campaign.results[-1]["status"] == "excluded"
    assert campaign.results[-1]["reason"] == "full index is partial"


def test_architecture_timeout_stops_descendants(tmp_path: Path) -> None:
    """Bound a dummy rendering process and terminate its sleeping descendant.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable workspace for dummy executable and logs.

    Returns
    -------
    None
        A timeout checkpoint survives; no Codira or Graphviz workload is run.
    """
    import sys

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    executable = tmp_path / "dummy-render"
    executable.write_text(
        "#!" + sys.executable + "\n"
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    executable.chmod(0o700)
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False, 0.5)
    result = campaign.command("arch", [str(executable), "arch"], repeats=3)
    assert result["status"] == "timeout"
    assert len(result["samples"]) == 1
    assert result["samples"][0]["timing_valid"] is False
    assert result["samples"][0]["timeout_seconds"] == 0.5
    child_pid = int(Path(result["stdout"]).read_text().strip())
    status = Path(f"/proc/{child_pid}/status")
    assert not status.exists() or "State:\tZ" in status.read_text()
    assert (tmp_path / "run/stages/arch/result.json").is_file()


def test_interrupt_records_checkpoint_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain an interrupted stage and clean its group before propagating Ctrl-C.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable checkpoint directory.
    monkeypatch : pytest.MonkeyPatch
        Replaces process launch, wait and group cleanup.

    Returns
    -------
    None
        No external workload is launched.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False)
    process = Mock(returncode=-15)
    process.wait.side_effect = KeyboardInterrupt
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    cleanup = Mock()
    monkeypatch.setattr(RUNNER, "terminate_group", cleanup)
    with pytest.raises(KeyboardInterrupt):
        campaign.command("arch", ["dummy", "arch"])
    cleanup.assert_called_once_with(process)
    checkpoint = json.loads((tmp_path / "run/stages/arch/result.json").read_text())
    assert checkpoint["status"] == "interrupted"
    assert checkpoint["samples"][0]["timing_valid"] is False


def test_interrupted_checkpoint_retries_without_failed_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resume an unfinished checkpoint independently of completed-stage retries.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable checkpoint directory.
    monkeypatch : pytest.MonkeyPatch
        Simulates a successful child process.

    Returns
    -------
    None
        The interrupted stage is retried without launching an external workload.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False)
    record = tmp_path / "run/stages/arch/result.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"key": "arch", "status": "interrupted"}))
    process = Mock(returncode=0)
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    result = campaign.command("arch", ["dummy", "arch"])
    assert result["status"] == "passed"
    assert len(result["samples"]) == 1


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("embedding_ready", [False, True])
def test_queryable_partial_keeps_structural_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extended: bool,
    embedding_ready: bool,
) -> None:
    """Run supported reads in both suites independently of embedding failure.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Isolated fake stage receipts.
    monkeypatch : pytest.MonkeyPatch
        Prevents real command execution.
    extended : bool
        Analyzer-style or stress execution path.
    embedding_ready : bool
        Actual embedding population prerequisite.

    Returns
    -------
    None
        No corpus indexing or benchmark campaign is launched.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "temporary_root": str(tmp_path),
                "extended": extended,
                "profiles": [{"id": "primary"}],
            }
        )
    )
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", False)
    invoked: list[list[str]] = []
    coverage = {
        "usable": True,
        "partial": True,
        "complete": False,
        "failed_paths": ["broken.py"],
    }
    output = tmp_path / "stdout.json"
    output.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "type": "function",
                        "name": "answer",
                        "file": "valid.py",
                        "line": 1,
                    }
                ]
            }
        )
    )

    def simulate(key: str, argv: list[str], *, repeats: int = 1) -> dict[str, Any]:
        """Retain fake outputs with separate structural and embedding readiness.

        Parameters
        ----------
        key : str
            Stage identifier.
        argv : list[str]
            Invocation under test.
        repeats : int
            Requested sample count.

        Returns
        -------
        dict
            Simulated checkpoint.
        """
        invoked.append(argv)
        status = (
            "partial"
            if key.endswith("index-full")
            else "failed"
            if key.endswith("index-embeddings") and not embedding_ready
            else "passed"
        )
        result = {
            "key": key,
            "status": status,
            "usable": True,
            "index_coverage": coverage,
            "embedding_complete": embedding_ready,
            "stdout": str(output),
        }
        campaign.results.append(result)
        return result

    monkeypatch.setattr(campaign, "command", simulate)
    member = campaign.repository(
        {
            "label": "fixture",
            "path": str(tmp_path),
            "configs": {"primary": "config.toml"},
            "repetitions": 2,
            "query": "answer",
        },
        {"id": "primary", "embeddings": True},
    )
    assert member is not None
    assert any(argv[1] == "cov" for argv in invoked)
    assert any(argv[1] == "refs" for argv in invoked)
    assert any("--embeddings-only" in argv for argv in invoked)
    assert any(argv[1] == "docs" for argv in invoked) == embedding_ready
    assert any(argv[1] == "ctx" for argv in invoked) == embedding_ready
    assert (
        sum(argv[1] == "index" and "--embeddings-only" not in argv for argv in invoked)
        == 1
    )
    reads = [r for r in campaign.results if r["key"].endswith(("/cov", "/refs"))]
    assert all(
        r["status"] == "partial" and r["comparison_group"] == "partial_coverage"
        for r in reads
    )


def test_partial_checkpoint_resume_keeps_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain partial samples and resume them even with failed-stage retry enabled.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable fake checkpoint directory.
    monkeypatch : pytest.MonkeyPatch
        Simulates a successful read process.

    Returns
    -------
    None
        Partial coverage remains distinct from complete timing success.
    """
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"temporary_root": str(tmp_path)}))
    campaign = RUNNER.Campaign(manifest, tmp_path / "run", True)
    launches = Mock()

    def simulate(
        argv: list[str], *, stdout: TextIO, **options: object
    ) -> SimpleNamespace:
        """Write a partial response without launching a subprocess.

        Parameters
        ----------
        argv : list[str]
            Captured invocation.
        stdout : TextIO
            Retained output stream.
        **options : object
            Unused process options.

        Returns
        -------
        types.SimpleNamespace
            Successful simulated process.
        """
        launches(argv)
        stdout.write(
            json.dumps(
                {
                    "status": "ok",
                    "index_coverage": {
                        "usable": True,
                        "partial": True,
                        "complete": False,
                    },
                }
            )
        )
        return SimpleNamespace(returncode=0, wait=Mock(return_value=0))

    monkeypatch.setattr(subprocess, "Popen", simulate)
    result = campaign.command("refs", ["codira", "refs", "answer", "--json"], repeats=2)
    resumed = campaign.command(
        "refs", ["codira", "refs", "answer", "--json"], repeats=2
    )
    assert result == resumed
    assert launches.call_count == 2
    assert result["status"] == "partial"
    assert all(
        not sample["timing_valid"] and sample["partial_timing_valid"]
        for sample in result["samples"]
    )
    assert Path(result["attempt_history"][0]).is_file()
    assert RUNNER.campaign_exit_status([resumed]) == 2


def test_unusable_retains_original_analysis_failure() -> None:
    """Keep zero-file indexing distinct from queryable partial analysis.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Failed paths and diagnostic reasons remain structured.
    """
    failure = {"path": "broken.py", "reason": "SyntaxError"}
    result = RUNNER.classify_sample(
        ["codira", "index", "--json"],
        json.dumps(
            {
                "summary": {"failed": 1, "indexed": 0},
                "failures": [failure],
                "index_coverage": {"usable": False, "partial": True},
            }
        ),
        "",
        0,
    )
    assert result["status"] == "unusable"
    assert result["analysis_failures"] == [failure]
    assert result["partial_timing_valid"] is False


def test_exclusion_recovery_is_new_identity_and_preserves_evidence(
    tmp_path: Path,
) -> None:
    """Prepare explicit exclusions while retaining original raw failure evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable original and recovery directories.

    Returns
    -------
    None
        No executable or campaign is launched by recovery preparation.
    """
    config = tmp_path / "original.toml"
    config.write_text('[plugins.analyzer-python]\nexclude_paths = ["vendor"]\n')
    manifest = tmp_path / "original.json"
    manifest.write_text(
        json.dumps(
            {
                "codira_root": "original",
                "artifact_root": "original-runs",
                "repositories": [
                    {"label": "fixture", "configs": {"primary": "original.toml"}}
                ],
            }
        )
    )
    original = tmp_path / "original-run"
    original.mkdir()
    identity: dict[str, Any] = {
        "manifest_sha256": RUNNER.digest(manifest),
        "configs": {"original.toml": RUNNER.digest(config)},
    }
    RUNNER.write(original / "identity.json", identity)
    stdout = original / "stdout"
    stderr = original / "stderr"
    stdout.write_text('{"failures":[{"path":"broken.py"}]}')
    stderr.write_text("original SyntaxError")
    RUNNER.write(
        original / "stages/index/result.json",
        {
            "status": "partial",
            "samples": [{"stdout": str(stdout), "stderr": str(stderr)}],
        },
    )
    before = {
        str(path.relative_to(original)): RUNNER.digest(path)
        for path in original.rglob("*")
        if path.is_file()
    }
    prepared = RUNNER.prepare_recovery(
        manifest, original, tmp_path / "recovery", ["fixture:python:broken.py"]
    )
    spec = json.loads(prepared.read_text())
    recovered_config = prepared.parent / spec["repositories"][0]["configs"]["primary"]
    assert (
        '"broken.py"' in recovered_config.read_text()
        and '"vendor"' in recovered_config.read_text()
    )
    assert spec["artifact_root"] != "original-runs"
    assert spec["recovery"]["original_identity"] == identity
    assert spec["recovery"]["operator_exclusions"] == {
        "fixture": {"python": ["broken.py"]}
    }
    evidence = spec["recovery"]["failure_evidence"][0]
    assert (
        Path(evidence["outputs"][1]["snapshot"]).read_text() == "original SyntaxError"
    )
    assert before == {
        str(path.relative_to(original)): RUNNER.digest(path)
        for path in original.rglob("*")
        if path.is_file()
    }
    assert RUNNER.digest(config) == identity["configs"]["original.toml"]
    with pytest.raises(ValueError, match="exists"):
        RUNNER.prepare_recovery(manifest, original, tmp_path / "recovery", [])
    config.write_text("changed = true")
    with pytest.raises(ValueError, match="configuration differs"):
        RUNNER.prepare_recovery(manifest, original, tmp_path / "changed-recovery", [])
    assert not (tmp_path / "changed-recovery").exists()


def test_baseline_preparation_and_resume_identity_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepare stress input offline and reject changed identity before execution.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable source and run receipts.
    monkeypatch : pytest.MonkeyPatch
        Blocks external process launch.

    Returns
    -------
    None
        A changed runner cannot silently resume old partial measurements.
    """
    import sys

    manifest = tmp_path / "source.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "stress",
                "repositories": [],
                "profiles": [],
                "capabilities": [],
                "coverage_gaps": [],
                "limitations": [],
                "codira_root": "source",
                "artifact_root": "source-runs",
            }
        )
    )
    prepared = RUNNER.prepare_recovery(manifest, None, tmp_path / "fresh-plan", [])
    spec = json.loads(prepared.read_text())
    assert spec["recovery"]["original_run"] is None
    assert spec["recovery"]["failure_evidence"] == []
    run = Path(spec["artifact_root"]) / "partial-run"
    RUNNER.write(
        run / "identity.json", {"launcher_sha256": "old-runner", "partial": True}
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["runner", str(prepared), "--run", "--resume", "--run-id", "partial-run"],
    )
    monkeypatch.setattr(subprocess, "check_output", Mock(return_value="commit\n"))
    launch = Mock()
    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(ValueError, match="resume identity differs"):
        RUNNER.main()
    launch.assert_not_called()
    assert json.loads((run / "identity.json").read_text())["partial"] is True
