"""Qualify the pinned serving image before any billable agent request.

Parameters
----------
None

Returns
-------
None
    Immutable offline image receipts separate from investigated fixture source.
"""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from codira.runtime_identity import runtime_identity

PROJECT_TEMP = Path("/home/marco/Personalia/Progetti/.Temp")
REQUIRED_ANALYZERS = frozenset(
    {"codira-analyzer-python", "codira-analyzer-typescript", "codira-analyzer-go"}
)


def _admitted_analyzers(runtime: object, source: dict[str, object]) -> bool:
    """Require every image analyzer to match source and panel analyzers to exist.

    Parameters
    ----------
    runtime : object
        Installed runtime receipt from the image.
    source : dict[str, object]
        Local approved source and analyzer fingerprint inventory.

    Returns
    -------
    bool
        True when the image contains the panel analyzers and no stale analyzer.
    """
    if not isinstance(runtime, dict):
        return False
    actual = runtime.get("analyzer_sources")
    expected = source.get("analyzer_sources")
    return (
        isinstance(actual, dict)
        and isinstance(expected, dict)
        and actual.keys() >= REQUIRED_ANALYZERS
        and all(expected.get(name) == digest for name, digest in actual.items())
    )


def qualify_image(runtime: str, image: str, evidence_root: Path) -> dict[str, object]:
    """Run isolated installed-product probes and retain their complete receipt.

    Parameters
    ----------
    runtime : str
        Admitted container runtime.
    image : str
        Immutable serving image digest.
    evidence_root : pathlib.Path
        Durable campaign state directory, separate from agent fixture source.

    Returns
    -------
    dict[str, object]
        Qualified image identity and actual registered schema evidence.

    Raises
    ------
    ValueError
        If qualification fails or a retained receipt has another identity.
    """
    installed = runtime_identity()
    expected = installed["source_sha256"]
    profile = Path("scripts/agent_efficiency/benchmark-codira.toml")
    profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
    receipt_path = evidence_root / "runtime-qualification.json"
    if receipt_path.exists():
        receipt = cast("dict[str, object]", json.loads(receipt_path.read_text()))
        if (
            receipt.get("image") != image
            or cast("dict[str, object]", receipt.get("runtime", {})).get(
                "source_sha256"
            )
            != expected
            or not _admitted_analyzers(receipt.get("runtime"), installed)
            or not {"python", "typescript", "go"}.issubset(
                cast("list[str]", receipt.get("active_analyzers", []))
            )
            or receipt.get("profile_sha256") != profile_hash
        ):
            raise ValueError(
                "retained runtime receipt differs; use a fresh campaign identity"
            )
        return receipt
    evidence_root.mkdir(parents=True, exist_ok=True)
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git is required for offline runtime qualification")
    with tempfile.TemporaryDirectory(
        prefix="ae-runtime-", dir=PROJECT_TEMP
    ) as temporary:
        scratch = Path(temporary)
        fixture = scratch / "fixture"
        fixture.mkdir()
        (fixture / "qualification.py").write_text(
            "class Qualification:\n    def probe(self):\n        return 42\n\ndef helper():\n    return Qualification().probe()\n"
        )
        (fixture / "other.py").write_text("def helper_two():\n    return 42\n")
        subprocess.run(
            (git, "init", "--quiet", str(fixture)), check=True, capture_output=True
        )
        subprocess.run(
            (git, "-C", str(fixture), "add", "--all"),
            check=True,
            capture_output=True,
        )
        completed = subprocess.run(
            (
                runtime,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=512",
                f"--mount=type=bind,src={fixture},dst=/workspace,rw",
                f"--mount=type=bind,src={scratch},dst=/temporary,rw",
                "--workdir=/workspace",
                image,
                "python",
                "/opt/codira/runtime_admission.py",
                "--root",
                "/workspace",
                "--query",
                "Qualification probe helper",
                "--expected-core-sha256",
                str(expected),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    (evidence_root / "runtime-qualification.stdout").write_text(completed.stdout)
    (evidence_root / "runtime-qualification.stderr").write_text(completed.stderr)
    if completed.returncode != 0:
        raise ValueError(
            "installed runtime qualification failed; inspect retained offline trace"
        )
    receipt = cast("dict[str, object]", json.loads(completed.stdout))
    if (
        cast("dict[str, object]", receipt.get("runtime", {})).get("source_sha256")
        != expected
        or not _admitted_analyzers(receipt.get("runtime"), installed)
        or receipt.get("profile_sha256") != profile_hash
    ):
        raise ValueError(
            "installed runtime does not match approved serving source and profile"
        )
    discovery = subprocess.run(
        (
            runtime,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=128m",
            image,
            "codira",
            "caps",
            "--json",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    (evidence_root / "runtime-capabilities.stdout").write_text(discovery.stdout)
    (evidence_root / "runtime-capabilities.stderr").write_text(discovery.stderr)
    if discovery.returncode != 0:
        raise ValueError("installed analyzer discovery failed")
    capabilities = json.loads(discovery.stdout)
    names = [item["analyzer_name"] for item in capabilities.get("analyzers", [])]
    if not {"python", "typescript", "go"}.issubset(names):
        raise ValueError("required panel analyzer is installed but inactive")
    receipt["active_analyzers"] = names
    receipt["image"] = image
    with receipt_path.open("x") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return receipt


def qualify_panel_freshness(
    runtime: str, image: str, evidence_root: Path
) -> dict[str, object]:
    """Replay the TypeScript edit, stale-source and stale-cursor task offline.

    Parameters
    ----------
    runtime : str
        Admitted runtime.
    image : str
        Exact image digest.
    evidence_root : pathlib.Path
        Fresh durable ignored probe record.

    Returns
    -------
    dict[str, object]
        Observed rejection and refreshed whole-source evidence facts.

    Raises
    ------
    ValueError
        If the replay cannot demonstrate the required freshness behavior.
    """
    from scripts.agent_efficiency.contracts import load_document
    from scripts.agent_efficiency.corpus import export_fixture

    source = Path("benchmarks/agent-efficiency/synthetic/typescript-workspace")
    fixture_document = load_document(
        Path(
            "benchmarks/agent-efficiency/panels/representative-v1/fixtures/typescript-workspace-synthetic.json"
        ),
        "fixture",
    )
    program = """from pathlib import Path
import json, subprocess
from codira.mcp.adapter import MCPAdapter
root=Path('/workspace')
def index():
    subprocess.run(['codira','index'],check=True,capture_output=True)
index()
adapter=MCPAdapter(root)
page=adapter.context_for_task('transform format conversion',limit=1)
cursor=page['page']['next_cursor']
assert isinstance(cursor,str)
identity=adapter.symbol('transform')['result']['symbols'][0]['identity']
before=adapter.symbol_evidence(identity)['result']
p=root/'impl.ts'
p.write_text(p.read_text().replace('text.toUpperCase()', '"fresh:" + text.toUpperCase()'))
try:
    adapter.symbol_evidence(identity)
except ValueError as error:
    assert 'source changed' in str(error)
else:
    raise AssertionError('changed source was accepted')
index()
try:
    adapter.context_for_task('transform format conversion',limit=1,cursor=cursor)
except ValueError:
    pass
else:
    raise AssertionError('old cursor was accepted')
adapter=MCPAdapter(root)
new_identity=adapter.symbol('transform')['result']['symbols'][0]['identity']
after=adapter.symbol_evidence(new_identity)['result']
assert 'fresh:' in after['source']
assert before['source_sha256'] != after['source_sha256']
print(json.dumps({'status':'passed','stale_source':'rejected','old_cursor':'rejected','new_source':'fresh marker present','before_sha256':before['source_sha256'],'after_sha256':after['source_sha256']}))
"""
    evidence_root.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="ae-fresh-", dir=PROJECT_TEMP) as temporary:
        scratch = Path(temporary)
        fixture = scratch / "fixture"
        export_fixture(source, str(fixture_document["revision"]), fixture)
        config = fixture / ".codira/config.toml"
        config.parent.mkdir()
        shutil.copy2("scripts/agent_efficiency/benchmark-codira.toml", config)
        completed = subprocess.run(
            (
                runtime,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                f"--mount=type=bind,src={fixture},dst=/workspace,rw",
                f"--mount=type=bind,src={scratch},dst=/temporary,rw",
                "--env=TMPDIR=/temporary",
                "--workdir=/workspace",
                image,
                "python",
                "-c",
                program,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    (evidence_root / "freshness.stdout").write_text(completed.stdout)
    (evidence_root / "freshness.stderr").write_text(completed.stderr)
    if completed.returncode != 0:
        raise ValueError("panel freshness qualification failed; inspect retained trace")
    receipt = cast("dict[str, object]", json.loads(completed.stdout))
    receipt["image"] = image
    (evidence_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt
