"""Exercise strict local documentation checks and the actual git rel alias.

Parameters
----------
None

Returns
-------
None
    Disposable repositories prevent any production fetch, push or release.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from mkdocs.utils.yaml import yaml_load

from scripts import check_docs, release_rel

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "git"


def _docs_fixture(root: Path, link: str) -> None:
    """Create minimal docs using the production link-validation settings.

    Parameters
    ----------
    root : pathlib.Path
        Owned fixture checkout.
    link : str
        Markdown to place in its documentation entry page.

    Returns
    -------
    None
        The source target exists outside docs; private artifact targets do not.
    """
    (root / "docs").mkdir()
    (root / "src").mkdir()
    (root / "src/helper.py").write_text("def helper(): pass\n")
    (root / "docs/index.md").write_text("# Fixture\n\n" + link + "\n")
    production = yaml_load((REPO_ROOT / "mkdocs.yml").read_text())
    (root / "mkdocs.yml").write_text(
        json.dumps({"site_name": "Fixture", "validation": production["validation"]})
    )


@pytest.mark.parametrize(
    "link",
    [
        "[existing repository source](../src/helper.py)",
        "[ignored measurements](../.artifacts/measurement/)",
        "[outside checkout](../../outside.md)",
        "[absolute filesystem source](/home/example/helper.py)",
    ],
)
def test_docs_gate_rejects_unpublishable_local_links(tmp_path: Path, link: str) -> None:
    """Fail on local-only evidence even when the source exists on the workstation.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable documentation root.
    link : str
        Unpublishable relative or filesystem link.

    Returns
    -------
    None
        The real strict MkDocs build returns nonzero and leaves no site tree.
    """
    _docs_fixture(tmp_path, link)
    assert check_docs.build_documentation(tmp_path) != 0
    assert not (tmp_path / "site").exists()


def test_docs_gate_accepts_published_links_and_plain_evidence(tmp_path: Path) -> None:
    """Keep valid docs links and local evidence descriptions publishable.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Disposable documentation root.

    Returns
    -------
    None
        Internal docs, immutable source URLs and plain local paths pass.
    """
    _docs_fixture(
        tmp_path,
        "[guide](guide.md)\n\n"
        "[source](https://github.com/marco0560/codira/blob/"
        "f2936cab8456ff27f5c2dae248bbabd15b69f2c0/src/codira/cli.py)\n\n"
        "Local evidence: `.artifacts/measurement/`.",
    )
    (tmp_path / "docs/guide.md").write_text("# Guide\n")
    assert check_docs.build_documentation(tmp_path) == 0
    assert not (tmp_path / "site").exists()


@pytest.mark.parametrize("skip_audit", [False, True])
def test_actual_git_rel_stops_before_remote_operations(
    tmp_path: Path, skip_audit: bool
) -> None:
    """Invoke the Git alias and reject broken docs before fetch or publication.

    Parameters
    ----------
    tmp_path : pathlib.Path
        Minimal owned Git repository, deliberately without a remote.
    skip_audit : bool
        Existing release-audit bypass must not bypass documentation checks.

    Returns
    -------
    None
        The real release entry point emits the link error and stops locally.
    """
    _docs_fixture(tmp_path, "[source](../src/helper.py)")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("")
    for name in ("release_rel.py", "scriptlib.py", "check_docs.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, scripts / name)
    subprocess.run([GIT, "init", "-b", "main", str(tmp_path)], check=True)
    alias = "!" + shlex.join([sys.executable, "-m", "scripts.release_rel"])
    subprocess.run([GIT, "-C", str(tmp_path), "config", "alias.rel", alias], check=True)
    env = {
        **os.environ,
        "PYTHON": sys.executable,
        "PYTHONPATH": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    if skip_audit:
        env["SKIP_RELEASE_AUDIT"] = "1"
    else:
        env.pop("SKIP_RELEASE_AUDIT", None)
    result = subprocess.run(
        [GIT, "-C", str(tmp_path), "rel"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "not found among documentation files" in result.stderr
    assert "Checking published documentation" in result.stdout
    assert "Sync with remote" not in result.stdout
    assert "Release pipeline completed" not in result.stdout


def test_git_rel_rechecks_pulled_docs_before_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop before publication if pulling introduces a documentation failure.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Replaces remote operations with controlled command outcomes.

    Returns
    -------
    None
        Both documentation gates are exercised; the second failure prevents push.
    """
    commands: list[tuple[str, ...]] = []
    docs_checks = 0

    def simulate(
        argv: Sequence[str], **options: object
    ) -> subprocess.CompletedProcess[str]:
        """Simulate pulled documentation becoming invalid without network access.

        Parameters
        ----------
        argv : collections.abc.Sequence[str]
            Release command under test.
        **options : object
            Existing subprocess options.

        Returns
        -------
        subprocess.CompletedProcess[str]
            Only the second documentation check fails.
        """
        nonlocal docs_checks
        commands.append(tuple(argv))
        if tuple(argv[-2:]) == ("-m", "scripts.check_docs"):
            docs_checks += 1
        return subprocess.CompletedProcess(argv, int(docs_checks == 2))

    monkeypatch.setattr(release_rel, "resolve_python", lambda: "python")
    monkeypatch.setattr(release_rel, "run", simulate)
    assert release_rel.main() == 1
    assert docs_checks == 2
    assert ("git", "fetch") in commands
    assert ("git", "pull", "--ff-only") in commands
    assert not any(command[:2] == ("git", "push") for command in commands)
