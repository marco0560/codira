"""Replay known correct, incomplete and subtly wrong panel patches offline."""
# ruff: noqa: EM101, EM102, TRY003

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from scripts.agent_efficiency.contracts import load_document
from scripts.agent_efficiency.corpus import export_fixture
from scripts.agent_efficiency.oracles import evaluate_oracle
from scripts.agent_efficiency.panels import panel_document_path, prepare_panel_fixture
from scripts.agent_efficiency.protected_runtime import ImageOracleExecutor
from scripts.agent_efficiency.runner import PROJECT_TEMP_ROOT
from scripts.run_agent_efficiency_phase6_pilot import install_protected_asset

BASE = Path("benchmarks/agent-efficiency")


def _replace(root: Path, relative: str, old: str, new: str) -> None:
    """Apply one curated edit only when its source anchor matches exactly.

    Parameters
    ----------
    root : pathlib.Path
        Disposable seeded fixture.
    relative, old, new : str
        Source path and exact before/after text.

    Returns
    -------
    None
        The changed source is suitable for a real patch application probe.
    """
    path = root / relative
    source = path.read_text()
    if source.count(old) != 1:
        raise ValueError(f"calibration anchor differs: {relative}")
    path.write_text(source.replace(old, new))


def _patch_case(root: Path, task_id: str, label: str) -> None:
    """Construct a source-curated patch with one controlled behavioral defect.

    Parameters
    ----------
    root : pathlib.Path
        Disposable seeded source tree.
    task_id, label : str
        Frozen patch task and correct/incomplete/subtly_wrong variant.

    Returns
    -------
    None
        Source edits and regression examples are ready for diff capture.
    """
    if task_id == "panel-p1":
        reduction = "    __reduce_ex__ = enum.pickle_by_enum_name\n"
        if label != "correct":
            reduction = "    # Enum reconstruction still uses its object value.\n"
        if label == "subtly_wrong":
            reduction = '    def __reduce_ex__(self, protocol):\n        return getattr, (type(self), "UNSET")\n'
        _replace(
            root,
            "src/click/_utils.py",
            "    UNSET = object()",
            reduction + "    UNSET = object()",
        )
        test = "import copy, pickle\nfrom click._utils import Sentinel\n\ndef test_member_identity():\n    for member in Sentinel:\n        assert copy.copy(member) is member\n        assert copy.deepcopy(member) is member\n        assert pickle.loads(pickle.dumps(member)) is member\n"
        test += '\nfrom click import Option\n\ndef test_option_identity():\n    option = Option(["--name"])\n    assert option.default is Sentinel.UNSET\n    for duplicate in (copy.copy, copy.deepcopy, lambda value: pickle.loads(pickle.dumps(value))):\n        copied = duplicate(option)\n        assert copied.name == "name"\n        assert copied.default is Sentinel.UNSET\n'
        (root / "tests/test_utils/test_calibration_sentinel.py").write_text(test)
    elif task_id == "panel-p2":
        replacement = (
            "if (isIgnored(input)) {"
            if label == "correct"
            else "if (false && isIgnored(input)) { // incomplete"
        )
        if label == "subtly_wrong":
            replacement = "if (isIgnored(input)) {"
        _replace(
            root, "lib/picomatch.js", "if (false && isIgnored(input)) {", replacement
        )
        if label == "subtly_wrong":
            _replace(
                root,
                "lib/picomatch.js",
                "      return returnObject ? result : false;\n    }\n\n    if (typeof opts.onMatch",
                "      return returnObject ? result : true;\n    }\n\n    if (typeof opts.onMatch",
            )
        (root / "test/calibration-ignore.js").write_text(
            "const assert=require('node:assert/strict'); let events=[]; const match=require('../')('*.js',{ignore:'skip.js',onResult:()=>events.push('result'),onIgnore:()=>events.push('ignore'),onMatch:()=>events.push('match')}); assert.equal(match('skip.js'),false); assert.deepEqual(events,['result','ignore']); events=[]; assert.equal(match('ok.js'),true); assert.deepEqual(events,['result','match']); events=[]; assert.equal(match('no.txt'),false); assert.deepEqual(events,['result']);\n"
        )
    elif task_id == "panel-p3":
        if label != "incomplete":
            _replace(root, "store/store.go", "cfg.Limit <= 0", "cfg.Limit < 0")
        if label != "subtly_wrong":
            _replace(
                root,
                "store/store.go",
                "len(text) > cfg.Limit",
                "cfg.Limit > 0 && len(text) > cfg.Limit",
            )
        (root / "store/calibration_test.go").write_text(
            'package store\nimport("testing"; "example.org/codira-benchmark-service/config")\nfunc TestZeroLimit(t *testing.T){ for _,s:=range []string{"","mixed"}{r,e:=Format(s,config.Config{Limit:0,Mode:"lower"});if e!=nil||r!=s{t.Fatal(r,e)}}; if _,e:=Format("a",config.Config{Limit:-1});e==nil{t.Fatal("negative accepted")}; r,e:=Format("ABCDE",config.Config{Limit:2,Mode:"lower"});if e!=nil||r!="ab"{t.Fatal(r,e)} }\n'
        )
    else:
        raise ValueError("unknown patch calibration task")


def _feature_case(root: Path, task_id: str, label: str) -> None:
    """Construct a controlled feature patch.

    Parameters
    ----------
    root : pathlib.Path
        Disposable seeded source tree.
    task_id, label : str
        Frozen task identity and calibration variant.

    Returns
    -------
    None
        Feature edits and regressions are ready for diff capture.
    """
    if task_id == "panel-f1":
        option = '    context_parser.add_argument(\n        "--max-results",\n        type=_item_limit,\n        default=10,\n        help="Complete items per page, 1..100 (default 10)",\n    )\n'
        if label == "subtly_wrong":
            option = option.replace("default=10", "default=100")
        _replace(
            root,
            "src/codira/cli_parser.py",
            '    context_parser.add_argument(\n        "--cursor",',
            option + '    context_parser.add_argument(\n        "--cursor",',
        )
        if label != "incomplete":
            _replace(
                root,
                "src/codira/cli_queries.py",
                "    limit = 10\n",
                '    limit = getattr(args, "max_results", 10)\n',
            )
        (root / "tests/test_calibration_limit.py").write_text(
            'import pytest\nfrom codira.cli_parser import build_parser\n\ndef test_limit():\n    parser=build_parser()\n    assert parser.parse_args(["ctx","x"]).max_results == 10\n    for value in (1,10,100):\n        assert parser.parse_args(["ctx","x","--max-results",str(value)]).max_results == value\n    for value in ("0","101","wrong"):\n        with pytest.raises(SystemExit):\n            parser.parse_args(["ctx","x","--max-results",value])\n'
        )
    elif task_id == "panel-f2":
        method = '\n    def capabilities(self) -> dict[str, bool]:\n        return {"case_conversion": True}\n\n'
        _replace(
            root,
            "service.py",
            'class Upper:\n    """Convert supplied text to upper case."""\n',
            'class Upper:\n    """Convert supplied text to upper case."""\n' + method,
        )
        _replace(
            root,
            "service.py",
            'class Lower:\n    """Convert supplied text to lower case."""\n',
            'class Lower:\n    """Convert supplied text to lower case."""\n' + method,
        )
        delegated = '        discover = getattr(self.plugin, "capabilities", None)\n        return {"case_conversion": bool(discover().get("case_conversion", False))} if callable(discover) else {"case_conversion": False}\n'
        if label == "incomplete":
            delegated = '        return {"case_conversion": False}\n'
        elif label == "subtly_wrong":
            delegated = '        return {"case_conversion": True}\n'
        _replace(
            root,
            "service.py",
            "        self.plugin = plugin\n",
            "        self.plugin = plugin\n\n    def capabilities(self) -> dict[str, bool]:\n"
            + delegated,
        )
        (root / "tests/test_calibration_capabilities.py").write_text(
            'from service import Adapter, Lower, Upper\n\nclass Legacy:\n    def render(self, text):\n        return text\n\nclass Extension(Legacy):\n    def capabilities(self):\n        return {"case_conversion": True}\n\ndef test_capabilities():\n    for plugin in (Lower(),Upper(),Extension()):\n        assert Adapter(plugin).capabilities() == {"case_conversion": True}\n    assert Adapter(Legacy()).capabilities() == {"case_conversion": False}\n    assert Adapter(Legacy()).render("Mixed") == "Mixed"\n'
        )
    elif task_id == "panel-f3":
        _replace(
            root,
            "impl.ts",
            "options: Options = {}): string",
            'options: Options = {}, suffix: string = ""): string',
        )
        _replace(root, "impl.ts", "return text;", "return text + suffix;")
        _replace(
            root,
            "impl.ts",
            'return options.mode === "lower" ? text.toLowerCase() : text.toUpperCase();',
            'return (options.mode === "lower" ? text.toLowerCase() : text.toUpperCase()) + suffix;',
        )
        _replace(
            root,
            "wrapper.ts",
            "options: Options = {}): string",
            'options: Options = {}, suffix: string = ""): string',
        )
        if label == "correct":
            _replace(
                root,
                "wrapper.ts",
                "enabled: options.enabled || true });",
                "enabled: options.enabled || true }, suffix);",
            )
        elif label == "subtly_wrong":
            _replace(root, "wrapper.ts", "transform(text,", "transform(text + suffix,")
        with (root / "tests.ts").open("a") as stream:
            stream.write(
                '\nimport {transform} from "./impl.ts";\nassert.equal(format("abc", {}, "end"), "ABCend");\nassert.equal(format("MiXeD", {mode:"lower"}, "END"), "mixedEND");\nassert.equal(transform("MiXeD", {enabled:false}, "end"), "MiXeDend");\n'
            )
    else:
        raise ValueError("unknown patch calibration task")


def qualify_patch_cases(
    runtime: str, image: str, evidence_root: Path, sources: dict[str, Path]
) -> dict[str, object]:
    """Apply all eighteen patch cases and execute their real protected probes.

    Parameters
    ----------
    runtime : str
        Admitted offline runtime.
    image : str
        Immutable image digest.
    evidence_root : pathlib.Path
        Fresh durable ignored calibration identity.
    sources : dict[str, pathlib.Path]
        Admitted source bindings for the panel fixtures.

    Returns
    -------
    dict[str, object]
        Case verdicts and exact patch digests; full traces remain private.

    Raises
    ------
    ValueError
        If Git is unavailable or a case differs from its expected verdict.
    """
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required for patch calibration")
    evidence_root.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, object]] = []
    bank = json.loads((BASE / "panels/representative-v1.json").read_text())
    for task in bank["tasks"]:
        if task["result_format"] != "workspace-diff":
            continue
        task_id, fixture_id = task["task_id"], task["fixture_id"]
        fixture = load_document(
            panel_document_path(BASE, "fixtures", fixture_id), "fixture"
        )
        oracle = load_document(panel_document_path(BASE, "oracles", task_id), "oracle")
        definition = cast("dict[str, list[dict[str, object]]]", oracle["definition"])[
            "all_of"
        ][0]
        for label in ("correct", "incomplete", "subtly_wrong"):
            case_root = evidence_root / f"{task_id}-{label}"
            case_root.mkdir()
            with tempfile.TemporaryDirectory(
                prefix="ae-patch-calibration-", dir=PROJECT_TEMP_ROOT
            ) as temporary:
                root = Path(temporary)
                agent, protected = root / "agent", root / "protected"
                export_fixture(sources[fixture_id], str(fixture["revision"]), agent)
                prepare_panel_fixture(agent, task_id)
                shutil.copytree(agent, protected)
                install_protected_asset(task_id, protected)
                baseline = subprocess.check_output(
                    (git, "-C", str(agent), "write-tree"), text=True
                ).strip()
                if task_id.startswith("panel-p"):
                    _patch_case(agent, task_id, label)
                else:
                    _feature_case(agent, task_id, label)
                subprocess.run(
                    (git, "-C", str(agent), "add", "--all"),
                    check=True,
                    capture_output=True,
                )
                patch = subprocess.check_output(
                    (git, "-C", str(agent), "diff", "--cached", "--binary", baseline)
                )
                artifact = agent / ".benchmark/fix.patch"
                artifact.parent.mkdir(exist_ok=True)
                artifact.write_bytes(patch)
                (case_root / "fix.patch").write_bytes(patch)
                outcome = evaluate_oracle(
                    definition,
                    result_root=agent,
                    result_path=".benchmark/fix.patch",
                    result_format="workspace-diff",
                    protected_root=protected,
                    trace_root=case_root / "oracle-trace",
                    command_executor=ImageOracleExecutor(
                        runtime, image, fixture_id, agent, 180
                    ),
                )
                expected = label == "correct"
                row = {
                    "task_id": task_id,
                    "case": label,
                    "passed": outcome.passed,
                    "expected": expected,
                    "patch_sha256": hashlib.sha256(patch).hexdigest(),
                    "checks": list(outcome.checks),
                }
                rows.append(row)
                (case_root / "result.json").write_text(json.dumps(row, indent=2) + "\n")
                if outcome.passed != expected:
                    raise ValueError(
                        f"protected calibration differs: {task_id}/{label}"
                    )
    receipt: dict[str, object] = {
        "image": image,
        "case_count": len(rows),
        "status": "passed",
        "cases": rows,
    }
    (evidence_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
