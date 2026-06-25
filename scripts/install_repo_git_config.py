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
        ("commit.gpgsign", "true"),
        ("commit.verbose", "true"),
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
            "!uv run python scripts/validate_repo.py",
        ),
        (
            "alias.fix",
            (
                "!uv run python scripts/run_repo_tool.py ruff check . --fix "
                "&& uv run python scripts/run_repo_tool.py ruff format ."
            ),
        ),
        (
            "alias.clean-repo",
            "!uv run python scripts/clean_repo.py",
        ),
        ("alias.clean-repo-dry", "!uv run python scripts/clean_repo.py --dry-run"),
        (
            "alias.re-clean",
            "!git clean-repo && git gen-issues && git gen-miles && git txz",
        ),
        (
            "alias.bootstrap",
            "!uv run python scripts/bootstrap_dev_environment.py",
        ),
        (
            "alias.new-decision",
            "!uv run python scripts/new_decision.py",
        ),
        (
            "alias.install-repo-config",
            "!uv run python scripts/install_repo_git_config.py",
        ),
        (
            "alias.docs-build",
            "!uv run mkdocs build --strict",
        ),
        (
            "alias.gen-issues",
            "!uv run python scripts/generate_github_snapshot.py issues --output issues.json",
        ),
        (
            "alias.gen-miles",
            "!uv run python scripts/generate_github_snapshot.py milestones --output milestones.json",
        ),
        (
            "alias.txz",
            (
                '!f() { name="${1:-repo}"; tmp="$(mktemp -d)"; '
                'trap \'rm -rf "$tmp"\' EXIT; mkdir -p "$tmp/repo"; '
                '{ git ls-files -z; printf "%s\\0" issues.json milestones.json; } '
                '| XZ_OPT="-9e -T0" tar --null -T - -cJf '
                "\"$PWD/$name.tar.xz\" --transform='s,^,repo/,'; }; f"
            ),
        ),
        (
            "alias.gen-zip-common",
            (
                '!f() { name="${1:-guidelines}"; tmp="$(mktemp -d)"; '
                'trap \'rm -rf "$tmp"\' EXIT; mkdir -p "$tmp/$name"; '
                '[ -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/chatgpt_guidelines.md" ] '
                '&& cp -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/chatgpt_guidelines.md" "$tmp/$name/"; '
                '[ -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/patch_discipline.md" ] '
                '&& cp -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/patch_discipline.md" "$tmp/$name/"; '
                '[ -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/anti-hallucination.md" ] '
                '&& cp -f "$HOME/OneDrive/Documenti/Fontshow/Comuni/anti-hallucination.md" "$tmp/$name/"; '
                'XZ_OPT="-9e -T0" tar --sort=name --mtime="UTC 1970-01-01" --owner=0 --group=0 '
                '--numeric-owner -C "$tmp" -cJf "$PWD/$name.tar.xz" "$name"; }; f'
            ),
        ),
        ("alias.release-audit", "!uv run python -m scripts.release_audit"),
        ("alias.release-check", "!uv run python -m scripts.release_system_selfcheck"),
        ("alias.rel", "!uv run python -m scripts.release_rel"),
        (
            "alias.safe-push",
            (
                "!uv run python -m scripts.release_audit && git fetch && "
                "git pull --ff-only && git push"
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
