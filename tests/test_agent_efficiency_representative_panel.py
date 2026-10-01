"""Qualify representative controls and immutable quality evidence offline."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from codira.runtime_identity import runtime_identity
from scripts.agent_efficiency.campaign_factory import build_campaign
from scripts.agent_efficiency.contracts import load_document
from scripts.agent_efficiency.corpus import export_fixture, verify_fixture
from scripts.agent_efficiency.examples import replay_examples
from scripts.agent_efficiency.full_campaign import validate_full_plan
from scripts.agent_efficiency.panels import panel_document_path, validate_panel_tasks
from scripts.agent_efficiency.quality import grade_quality, persist_adjudication
from scripts.agent_efficiency.runtime_qualification import qualify_image
from scripts.generate_agent_efficiency_panel import generated_documents
from scripts.run_agent_efficiency_phase6_pilot import (
    _semantic_review_pending,
    prompt_for_attempt,
    runtime_profile_fingerprint,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

BASE = Path("benchmarks/agent-efficiency")


def _spec() -> dict[str, object]:
    """Construct fresh offline controls from the frozen public panel.

    Parameters
    ----------
    None

    Returns
    -------
    dict[str, object]
        Qualification-only specification; never authorizes a paid request.
    """
    result = json.loads(
        (BASE / "campaign-specs/codira-efficacy-campaign-002.json").read_text()
    )
    bank = json.loads((BASE / "panels/representative-v1.json").read_text())
    result.update(
        campaign_id="factory-representative-001",
        stage="representative-campaign",
        repetitions=1,
        task_ids=[row["task_id"] for row in bank["tasks"]],
        panel_id="representative-v1",
        runtime_source_fingerprint=runtime_identity()["source_sha256"],
        runtime_profile_fingerprint=runtime_profile_fingerprint(),
        treatment_protocol={
            "version": "mcp-optional-v3",
            "agent_instruction": "Use the prepared offline environment and satisfy the exact task.",
            "codira_mcp_instruction": "Available Codira tools may be used when helpful.",
        },
    )
    return cast("dict[str, object]", result)


def test_panel_generation_balance_and_factory() -> None:
    """Admit 24 tasks without changing the legacy six-task factory contract.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Generation, holdout balance, shared prompts and 48-slot plans agree.
    """
    assert all(
        path.read_text() == content for path, content in generated_documents().items()
    )
    spec = _spec()
    manifest, plan = build_campaign(spec, BASE)
    assert plan["factory_version"] == "1.1"
    assert len(validate_full_plan(manifest, plan, int(str(spec["seed"])))) == 48
    assert prompt_for_attempt("task", "baseline", manifest) == prompt_for_attempt(
        "task", "codira-mcp", manifest
    )
    tasks = {
        identifier: load_document(
            panel_document_path(BASE, "tasks", identifier), "task"
        )
        for identifier in cast("list[str]", spec["task_ids"])
    }
    validate_panel_tasks(tasks, spec)
    tasks["panel-n1"]["split"] = "holdout"
    with pytest.raises(ValueError, match="split"):
        validate_panel_tasks(tasks, spec)


def test_snapshot_admission_and_export(tmp_path: Path) -> None:
    """Bind synthetic fixture bytes, license and history-free export.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable export destination.

    Returns
    -------
    None
        Source inventories admit exactly and exports contain staged files.
    """
    source = BASE / "synthetic/python-service"
    fixture = load_document(
        panel_document_path(BASE, "fixtures", "python-service-synthetic"), "fixture"
    )
    receipt = verify_fixture(fixture, source)
    export_fixture(source, receipt.revision, tmp_path / "export")
    assert (tmp_path / "export/service.py").read_bytes() == (
        source / "service.py"
    ).read_bytes()
    fixture["license_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="license"):
        verify_fixture(fixture, source)


def test_runtime_receipt_rejects_old_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an old serving image using no provider call or credential.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Private durable evidence substitute.
    monkeypatch : pytest.MonkeyPatch
        Container substitute returning a deliberately wrong source receipt.

    Returns
    -------
    None
        Qualification fails with complete stdout/stderr evidence retained.
    """

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return an old image receipt for the isolated container invocation.

        Parameters
        ----------
        argv : list[str]
            Credential-free command vector.
        kwargs : object
            Unused process settings.

        Returns
        -------
        subprocess.CompletedProcess[str]
            A source mismatch for the image, success for fixture Git setup.
        """
        del kwargs
        if "--network=none" in argv:
            assert "--read-only" in argv and not any(
                "OPENROUTER" in item for item in argv
            )
            body = {
                "runtime": {"source_sha256": "0" * 64},
                "profile_sha256": runtime_profile_fingerprint(),
            }
            return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(ValueError, match="approved serving source"):
        qualify_image("podman", "public@sha256:" + "a" * 64, tmp_path / "evidence")
    assert (tmp_path / "evidence/runtime-qualification.stdout").exists()
    assert not (tmp_path / "evidence/runtime-qualification.json").exists()


def test_pending_review_is_not_an_executable_failure() -> None:
    """Keep semantic review separate from an actually failing protected probe.

    Parameters
    ----------
    None

    Returns
    -------
    None
        Composite semantic-pending and protected-failure cases are distinct.
    """
    pending = [
        "all_of:failed",
        "all_of[0].patch.protected_command:passed",
        "all_of[1].quality[causal]:review_required",
    ]
    assert _semantic_review_pending(pending)
    assert not _semantic_review_pending(
        pending + ["all_of[0].patch.protected_command:failed"]
    )
    assert not _semantic_review_pending(pending + ["quality[fact]:contradicted"])


def test_adjudication_is_quote_bound_and_append_only(tmp_path: Path) -> None:
    """Record equivalent wording while retaining the original pending report.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Private receipt destination.

    Returns
    -------
    None
        Quoted evidence binds exact inputs and a second write is rejected.
    """
    answer = (
        "Pickling reconstructs by value; shallow copying already preserves identity."
    )
    rubric: Mapping[str, object] = {
        "criteria": [
            {
                "id": "cause",
                "dimension": "causality",
                "semantic": True,
                "requirement": "Distinguish pickling from copying.",
            }
        ]
    }
    original = grade_quality(answer, rubric)
    review = {
        "reviewer": "calibration-reference",
        "answer_sha256": original["answer_sha256"],
        "rubric_sha256": original["rubric_sha256"],
        "decisions": [
            {
                "id": "cause",
                "status": "supported",
                "reason": "States both required behaviors.",
                "evidence": answer,
            }
        ],
    }
    path = tmp_path / "receipt.json"
    report = persist_adjudication(answer, rubric, review, path)
    assert report["original"] == original
    with pytest.raises(FileExistsError):
        persist_adjudication(answer, rubric, review, path)


def test_example_replay_is_isolated_and_traceable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep runnable examples inside a constrained container and retain output.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Public fixture and private trace substitutes.
    monkeypatch : pytest.MonkeyPatch
        Container substitute proving the actual invocation settings.

    Returns
    -------
    None
        Output bytes are retained and expected-output judgment stays pending.
    """
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "module.py").write_text("VALUE=42\n")

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        """Capture container isolation and return a complete public example output.

        Parameters
        ----------
        argv : list[str]
            Shell-free host container command.
        kwargs : object
            Captured process settings.

        Returns
        -------
        subprocess.CompletedProcess[bytes]
            Successful example stdout and stderr.
        """
        assert (
            "--network=none" in argv
            and "--memory=512m" in argv
            and kwargs["timeout"] == 60
        )
        return subprocess.CompletedProcess(argv, 0, b"42\n", b"")

    monkeypatch.setattr(subprocess, "run", run)
    answer = "```python\nfrom module import VALUE\nprint(VALUE)\n```\n"
    report = replay_examples(
        answer, "podman", "public@sha256:" + "a" * 64, fixture, tmp_path / "trace"
    )
    assert report["answer_sha256"] == hashlib.sha256(answer.encode()).hexdigest()
    assert report["expected_output_accuracy"] == "review_required"
    assert (tmp_path / "trace/example-0.stdout").read_bytes() == b"42\n"
