"""Test deterministic protected grading for agent-efficiency benchmark tasks."""

from __future__ import annotations

import hashlib
import json
import sys
from typing import TYPE_CHECKING

import pytest

from scripts.agent_efficiency.contracts import ContractError
from scripts.agent_efficiency.oracles import ProtectedEvaluator, evaluate_oracle

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def write_result(root: Path, payload: object) -> None:
    """Write one candidate result artifact.

    Parameters
    ----------
    root : pathlib.Path
        Agent result root.
    payload : object
        JSON-compatible artifact payload.

    Returns
    -------
    None
        The fixture result is written below ``.benchmark``.
    """

    path = root / ".benchmark" / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def protected_fixture(root: Path) -> None:
    """Create a pristine source tree and independent protected test.

    Parameters
    ----------
    root : pathlib.Path
        Protected fixture root.

    Returns
    -------
    None
        Source and verifier files are written.
    """

    (root / "app.py").write_text("VALUE = 'before'\n", encoding="utf-8")
    (root / "verify.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(Path('app.py').read_text() != \"VALUE = 'after'\\n\")\n",
        encoding="utf-8",
    )


def test_symbol_path_and_normalized_artifact_oracles_pass(tmp_path: Path) -> None:
    """Accept valid symbol, path, and normalized-artifact evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary isolated agent and protected roots.

    Returns
    -------
    None
        The combined deterministic oracle passes.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    write_result(
        result_root,
        {
            "symbols": [
                {"qualified_name": "codira.mcp.context_for_task", "kind": "method"}
            ],
            "paths": ["src/codira/mcp/adapter.py"],
            "summary": "  deterministic   output ",
        },
    )
    definition = {
        "all_of": [
            {"contains_symbols": [{"qualified_name": "codira.mcp.context_for_task"}]},
            {"contains_paths": ["src/codira/mcp/adapter.py"]},
            {"normalized_artifact": {"summary": "deterministic output"}},
        ]
    }
    assert evaluate_oracle(
        definition, result_root=result_root, protected_root=protected
    ).passed


def test_missing_malformed_and_false_positive_results_fail(tmp_path: Path) -> None:
    """Reject missing, malformed, and invented result evidence.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary isolated agent and protected roots.

    Returns
    -------
    None
        Missing and malformed artifacts raise; false positives fail.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    with pytest.raises(ContractError, match="missing or malformed"):
        evaluate_oracle(
            {"contains_paths": ["truth"]},
            result_root=result_root,
            protected_root=protected,
        )
    path = result_root / ".benchmark" / "result.json"
    path.parent.mkdir()
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ContractError, match="malformed"):
        evaluate_oracle(
            {"contains_paths": ["truth"]},
            result_root=result_root,
            protected_root=protected,
        )
    write_result(result_root, {"paths": ["reported-but-wrong"]})
    outcome = evaluate_oracle(
        {"contains_paths": ["truth"]}, result_root=result_root, protected_root=protected
    )
    assert not outcome.passed


def test_text_artifact_oracle_requires_each_declared_fact(tmp_path: Path) -> None:
    """Grade a natural Markdown task artifact without a hidden JSON schema.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent and protected roots.

    Returns
    -------
    None
        The text primitive accepts required facts and rejects omissions.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    (result_root / "answer.md").write_text(
        "MCPAdapter.context_for_task lives in src/codira/mcp/adapter.py\n",
        encoding="utf-8",
    )
    definition = {
        "text_contains": [
            "MCPAdapter.context_for_task",
            "src/codira/mcp/adapter.py",
        ]
    }
    assert evaluate_oracle(
        definition,
        result_root=result_root,
        result_path="answer.md",
        result_format="text",
        protected_root=protected,
    ).passed
    (result_root / "answer.md").write_text(
        "MCPAdapter.context_for_task\n", encoding="utf-8"
    )
    assert not evaluate_oracle(
        definition,
        result_root=result_root,
        result_path="answer.md",
        result_format="text",
        protected_root=protected,
    ).passed


def test_patch_oracle_uses_pristine_copy_and_rejects_tampering(tmp_path: Path) -> None:
    """Apply only a valid patch and run the independent protected test.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent and protected fixture roots.

    Returns
    -------
    None
        A valid patch passes and tampered patch content fails.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    protected_fixture(protected)
    write_result(result_root, {})
    patch = result_root / ".benchmark" / "fix.patch"
    patch.write_text(
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 'before'\n+VALUE = 'after'\n",
        encoding="utf-8",
    )
    definition = {
        "patch_applies_and_tests_pass": {
            "patch_path": ".benchmark/fix.patch",
            "command": [sys.executable, "verify.py"],
        }
    }
    assert evaluate_oracle(
        definition, result_root=result_root, protected_root=protected
    ).passed
    (protected / "fail.py").write_text("raise SystemExit(1)\n", encoding="utf-8")
    failing_command = {
        "patch_applies_and_tests_pass": {
            **definition["patch_applies_and_tests_pass"],
            "command": [sys.executable, "fail.py"],
        }
    }
    assert not evaluate_oracle(
        failing_command, result_root=result_root, protected_root=protected
    ).passed
    patch.write_text("tampered", encoding="utf-8")
    assert not evaluate_oracle(
        definition, result_root=result_root, protected_root=protected
    ).passed
    patch.write_text(
        "--- a/../../escaped.py\n+++ b/../../escaped.py\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="patch header path escapes"):
        evaluate_oracle(definition, result_root=result_root, protected_root=protected)
    patch.write_text(
        "diff --git a/../../escaped.py b/../../escaped.py\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="patch header path escapes"):
        evaluate_oracle(definition, result_root=result_root, protected_root=protected)
    patch.write_text(
        "diff --git a/app.py b/app.py\nrename from app.py\nrename to ../../escaped.py\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="patch header path escapes"):
        evaluate_oracle(definition, result_root=result_root, protected_root=protected)
    outside = tmp_path / "outside.patch"
    outside.write_text(
        "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 'before'\n+VALUE = 'after'\n",
        encoding="utf-8",
    )
    patch.unlink()
    patch.symlink_to(outside)
    with pytest.raises(ContractError, match="patch_path escapes"):
        evaluate_oracle(definition, result_root=result_root, protected_root=protected)


def test_custom_evaluator_requires_declared_isolation(tmp_path: Path) -> None:
    """Permit only registered evaluator code with explicit isolation claims.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent and protected fixture roots.

    Returns
    -------
    None
        Registered evaluators pass; identity-access requests are rejected.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    write_result(result_root, {"answer": "ok"})
    script = protected / "evaluators" / "answer.py"
    script.parent.mkdir()
    script.write_text("# protected deterministic evaluator\n", encoding="utf-8")
    definition = {
        "custom_evaluator": {
            "evaluator_id": "answer",
            "no_llm": True,
            "variant_identity_access": False,
            "rationale": "The protected evaluator checks a fixed result field.",
            "script_path": "evaluators/answer.py",
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        }
    }

    def evaluator(result: Mapping[str, object], _root: Path) -> bool:
        """Accept the expected result without variant identity access.

        Parameters
        ----------
        result : collections.abc.Mapping[str, object]
            Agent result object supplied to the protected evaluator.
        _root : pathlib.Path
            Protected fixture root, intentionally unused by this evaluator.

        Returns
        -------
        bool
            Whether the result has the expected deterministic value.
        """

        return result["answer"] == "ok"

    registered = ProtectedEvaluator(
        evaluator=evaluator,
        script_path="evaluators/answer.py",
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
    )
    assert evaluate_oracle(
        definition,
        result_root=result_root,
        protected_root=protected,
        evaluators={"answer": registered},
    ).passed
    write_result(result_root, {"answer": "not-ok"})
    assert not evaluate_oracle(
        definition,
        result_root=result_root,
        protected_root=protected,
        evaluators={"answer": registered},
    ).passed
    write_result(result_root, {"answer": "ok"})
    without_llm_declaration = {
        "custom_evaluator": {
            key: value
            for key, value in definition["custom_evaluator"].items()
            if key != "no_llm"
        }
    }
    with pytest.raises(ContractError, match="prohibit LLM"):
        evaluate_oracle(
            without_llm_declaration,
            result_root=result_root,
            protected_root=protected,
            evaluators={"answer": registered},
        )
    empty_rationale = {
        "custom_evaluator": {
            **definition["custom_evaluator"],
            "rationale": "",
        }
    }
    with pytest.raises(ContractError, match="rationale"):
        evaluate_oracle(
            empty_rationale,
            result_root=result_root,
            protected_root=protected,
            evaluators={"answer": registered},
        )
    mismatched_binding = ProtectedEvaluator(
        evaluator=evaluator,
        script_path="evaluators/answer.py",
        script_sha256="0" * 64,
    )
    with pytest.raises(ContractError, match="registry binding"):
        evaluate_oracle(
            definition,
            result_root=result_root,
            protected_root=protected,
            evaluators={"answer": mismatched_binding},
        )
    tampered = {
        "custom_evaluator": {
            **definition["custom_evaluator"],
            "script_sha256": "0" * 64,
        }
    }
    with pytest.raises(ContractError, match="script identity"):
        evaluate_oracle(
            tampered,
            result_root=result_root,
            protected_root=protected,
            evaluators={"answer": registered},
        )
    unsafe = {
        "custom_evaluator": {
            "evaluator_id": "answer",
            "no_llm": True,
            "variant_identity_access": True,
            "rationale": "This must be rejected.",
            "script_path": "evaluators/answer.py",
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        }
    }
    with pytest.raises(ContractError, match="variant identity"):
        evaluate_oracle(
            unsafe,
            result_root=result_root,
            protected_root=protected,
            evaluators={"answer": registered},
        )


def test_command_and_boolean_primitives_reject_shells_and_bad_nodes(
    tmp_path: Path,
) -> None:
    """Exercise protected command and boolean-composition boundary failures.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Temporary agent and protected fixture roots.

    Returns
    -------
    None
        A safe command passes; shell and malformed-node inputs are rejected.
    """

    result_root = tmp_path / "agent"
    protected = tmp_path / "protected"
    result_root.mkdir()
    protected.mkdir()
    write_result(result_root, {"paths": ["present"]})
    (protected / "pass.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    safe = {
        "all_of": [
            {"command_passes": [sys.executable, "pass.py"]},
            {
                "any_of": [
                    {"contains_paths": ["missing"]},
                    {"contains_paths": ["present"]},
                ]
            },
        ]
    }
    assert evaluate_oracle(
        safe, result_root=result_root, protected_root=protected
    ).passed
    with pytest.raises(ContractError, match="cannot invoke a shell"):
        evaluate_oracle(
            {"command_passes": ["sh", "-c", "true"]},
            result_root=result_root,
            protected_root=protected,
        )
    with pytest.raises(ContractError, match="cannot invoke a shell"):
        evaluate_oracle(
            {"command_passes": ["/bin/dash", "script.sh"]},
            result_root=result_root,
            protected_root=protected,
        )
    (protected / "side_effect.py").write_text(
        "from pathlib import Path\nPath('side-effect').write_text('ran')\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="children must be objects"):
        evaluate_oracle(
            {
                "all_of": [
                    {"command_passes": [sys.executable, "side_effect.py"]},
                    "not-an-oracle-object",
                ]
            },
            result_root=result_root,
            protected_root=protected,
        )
    assert not (protected / "side-effect").exists()
    with pytest.raises(ContractError, match="exactly one primitive"):
        evaluate_oracle(
            {"contains_paths": [], "any_of": []},
            result_root=result_root,
            protected_root=protected,
        )
