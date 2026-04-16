#!/usr/bin/env python3
"""Install deterministic repo-local Git configuration.

Responsibilities
----------------
- Define stable Git config entries such as hooks paths, commit template, and
  helpful aliases.
- Apply all entries via `git config --local` to the repository.
- Mirror the repo-local alias set used by this checkout without installing
  personal identity, remote URLs, or credentials.

Design principles
-----------------
Configuration is explicit, deterministic, and avoids personal or
environment-specific overrides.
Aliases that contact GitHub use the caller's own configured `gh`/Git
authentication and do not embed credentials.

Architectural role
------------------
This script belongs to the **tooling layer** ensuring consistent Git behavior
for contributors.
"""

from __future__ import annotations

import shutil
import subprocess

GIT_EXE = shutil.which("git") or "git"


def git_alias_entries() -> list[tuple[str, str]]:
    """
    Return repo-local Git config entries to install.

    Parameters
    ----------
    None

    Returns
    -------
    list[tuple[str, str]]
        Ordered ``(key, value)`` Git config entries.
    """

    return [
        ("core.hooksPath", ".githooks"),
        ("commit.template", ".gitmessage"),
        ("pull.ff", "only"),
        ("pull.rebase", "false"),
        ("rebase.autostash", "true"),
        ("alias.st", "status"),
        ("alias.co", "checkout"),
        ("alias.br", "branch"),
        ("alias.ci", "commit"),
        ("alias.lg", "log --oneline --graph --decorate -50"),
        (
            "alias.check",
            (
                "!bash -lc 'source .venv/bin/activate && black --check . && "
                "ruff check . && mypy . && pytest -q'"
            ),
        ),
        ("alias.fix", "!ruff check . --fix"),
        (
            "alias.clean-repo",
            "!bash scripts/run_with_repo_python.sh scripts/clean_repo.py",
        ),
        (
            "alias.clean-repo-dry",
            "!python scripts/clean_repo.py --dry-run",
        ),
        (
            "alias.re-clean",
            "!git clean-repo && git gen-issues && git gen-miles && git txz",
        ),
        (
            "alias.bootstrap",
            (
                "!bash scripts/run_with_repo_python.sh "
                "scripts/bootstrap_dev_environment.py"
            ),
        ),
        (
            "alias.new-decision",
            "!bash scripts/run_with_repo_python.sh scripts/new_decision.py",
        ),
        (
            "alias.install-repo-config",
            (
                "!bash scripts/run_with_repo_python.sh "
                "scripts/install_repo_git_config.py"
            ),
        ),
        (
            "alias.docs-build",
            "!bash -lc 'source .venv/bin/activate && mkdocs build --strict'",
        ),
        (
            "alias.gen-issues",
            (
                "!f(){ rm -f issues.json; timeout 10s gh api graphql "
                '-f query=\'query {repository(owner: "marco0560", '
                'name: "codira") {issues(first: 100, states: OPEN, '
                "orderBy: {field: CREATED_AT, direction: ASC}) {nodes "
                "{number, title, body, url, labels(first: 20) "
                "{nodes {name}}, milestone {number, title}, comments "
                "{totalCount}}}}}' > issues.json; }; f"
            ),
        ),
        (
            "alias.gen-miles",
            (
                "!f() { rm -f milestones.json; timeout 10s gh api graphql "
                '-f query=\'query {repository(owner: "marco0560", '
                'name: "codira") {milestones(first: 20, states: OPEN, '
                "orderBy: {field: DUE_DATE, direction: ASC}) "
                "{nodes {number, title, dueOn, progressPercentage, issues(first: 100) "
                "{nodes {number, title, state, labels(first: 20) "
                "{nodes {name}}}}}}}}' > milestones.json ; }; f"
            ),
        ),
        (
            "alias.txz",
            (
                '!f(){ name="${1:-repo}"; tmp="$(mktemp -d)"; '
                "trap 'rm -rf \"$tmp\"' EXIT; rsync -a --delete "
                '--exclude=".git" --exclude="*.tar.xz" --exclude=".codira" '
                '--exclude=".venv" --exclude="node_modules" '
                '--exclude="__pycache__" ./ "$tmp/repo/" && '
                'XZ_OPT="-9e -T0" tar -C "$tmp" -cJf "$PWD/$name.tar.xz" '
                "repo; }; f"
            ),
        ),
        ("alias.release-audit", "!bash scripts/release_audit.sh"),
        ("alias.release-check", "!bash scripts/release_system_selfcheck.sh"),
        ("alias.rel", "!bash scripts/release_rel.sh"),
        (
            "alias.safe-push",
            (
                "!bash -lc 'bash scripts/release_audit.sh && git fetch && "
                "git pull --ff-only && git push'"
            ),
        ),
    ]


def main() -> int:
    """
    Apply the repo-local Git configuration entries.

    Parameters
    ----------
    None

    Returns
    -------
    int
        Process exit code.
    """

    for key, value in git_alias_entries():
        subprocess.run([GIT_EXE, "config", "--local", key, value], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
