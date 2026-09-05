"""Run the Textual installer or its equivalent non-interactive commands."""
# ruff: noqa: TRY003, TRY004, TRY300, EM101

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from subprocess import CalledProcessError
from typing import TYPE_CHECKING

from codira_installer.controller import InstallerController
from codira_installer.execution import InstallationCancelled, apply_plan
from codira_installer.models import (
    EnvironmentKind,
    EnvironmentTarget,
    InstallationProfile,
    InstallerRequest,
    InstallSource,
    PackageManager,
    RuntimeKind,
    RuntimeOperation,
    RuntimeTarget,
    WorkspaceRegistration,
)
from codira_installer.plan import load_plan, render_plan, validate_plan

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codira_installer.models import InstallPlan


def _parser() -> argparse.ArgumentParser:
    """Build the standalone installer command parser.

    Parameters
    ----------
    None

    Returns
    -------
    argparse.ArgumentParser
        Parser for the TUI, plan export, apply, and resume entry points.
    """
    parser = argparse.ArgumentParser(prog="codira-installer")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--plan", type=Path, metavar="PATH", help="write a plan JSON file"
    )
    actions.add_argument(
        "--apply", type=Path, metavar="PATH", help="apply a plan JSON file"
    )
    actions.add_argument(
        "--resume", type=Path, metavar="PATH", help="resume a plan JSON file"
    )
    parser.add_argument(
        "--journal",
        type=Path,
        default=Path(".codira-installer-journal.json"),
        help="credential-free resume journal path",
    )
    parser.add_argument(
        "--source", choices=tuple(InstallSource), default=InstallSource.PYPI
    )
    parser.add_argument(
        "--checkout", type=Path, help="cloned Codira root for local-checkout"
    )
    parser.add_argument(
        "--target", choices=tuple(EnvironmentKind), default=EnvironmentKind.CURRENT
    )
    parser.add_argument(
        "--environment", type=Path, help="existing or new environment root"
    )
    parser.add_argument("--runtime", choices=tuple(RuntimeKind))
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument(
        "--operation", choices=tuple(RuntimeOperation), default=RuntimeOperation.INSTALL
    )
    parser.add_argument("--workspace")
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--workspace-state-root", type=Path)
    parser.add_argument("--workspace-config-file", type=Path)
    parser.add_argument("--model-store", type=Path)
    parser.add_argument(
        "--manager", choices=tuple(PackageManager), default=PackageManager.UV
    )
    parser.add_argument(
        "--profile",
        choices=tuple(InstallationProfile),
        default=InstallationProfile.RECOMMENDED,
    )
    parser.add_argument(
        "--package", action="append", default=[], help="official Advanced package"
    )
    return parser


def _request(args: argparse.Namespace) -> InstallerRequest:
    """Convert command options to the same request used by the Textual app.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed standalone command options.

    Returns
    -------
    codira_installer.models.InstallerRequest
        Typed request ready for shared plan resolution.

    Raises
    ------
    ValueError
        If target path cardinality is incompatible with the selected target.
    """
    target_kind = EnvironmentKind(args.target)
    target = EnvironmentTarget(target_kind, args.environment)
    if args.runtime is None:
        runtime_kind = (
            RuntimeKind.MANAGED
            if target_kind is EnvironmentKind.CURRENT
            else RuntimeKind(target_kind)
        )
        runtime_root = target.path
    else:
        runtime_kind = RuntimeKind(args.runtime)
        runtime_root = args.runtime_root
    workspace = None
    if args.workspace is not None:
        if args.repository is None:
            raise ValueError("--workspace requires --repository")
        workspace = WorkspaceRegistration(
            args.workspace,
            args.repository,
            args.workspace_state_root,
            args.workspace_config_file,
        )
    source = InstallSource(args.source)
    checkout = args.checkout
    if source is InstallSource.LOCAL_CHECKOUT and checkout is None:
        checkout = Path.cwd()
    return InstallerRequest(
        target=target,
        source=source,
        checkout=checkout,
        manager=PackageManager(args.manager),
        profile=InstallationProfile(args.profile),
        packages=tuple(args.package),
        runtime=RuntimeTarget(runtime_kind, runtime_root),
        operation=RuntimeOperation(args.operation),
        workspace=workspace,
        model_store=args.model_store,
    )


def _write_plan(path: Path, content: str) -> None:
    """Atomically write exported plan content after it has validated.

    Parameters
    ----------
    path : pathlib.Path
        Requested plan output path.
    content : str
        Canonical plan JSON.

    Returns
    -------
    None
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _read_plan(path: Path) -> InstallPlan:
    """Read and validate a portable plan JSON file.

    Parameters
    ----------
    path : pathlib.Path
        Existing plan JSON path.

    Returns
    -------
    codira_installer.models.InstallPlan
        Validated typed plan.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("installer plan JSON must contain an object")
    return load_plan(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Run interactive setup, export a plan, or apply/resume a plan headlessly.

    Parameters
    ----------
    argv : collections.abc.Sequence[str] | None, optional
        Command arguments, or process arguments when omitted.

    Returns
    -------
    int
        Zero on success, one for an apply failure, or two for invalid input.
    """
    args = _parser().parse_args(argv)
    try:
        if args.plan is not None:
            controller = InstallerController(_request(args), args.journal)
            plan = controller.resolve()
            _write_plan(args.plan, render_plan(plan))
            print(f"Wrote validated installer plan to {args.plan}")
            return 0
        if args.apply is not None or args.resume is not None:
            plan_path = args.apply if args.apply is not None else args.resume
            plan = _read_plan(plan_path)
            validate_plan(plan)
            journal = apply_plan(plan, args.journal)
            print(f"Completed {len(journal.results)} installer steps.")
            return 0
        from codira_installer.app import InstallerApp

        InstallerApp(InstallerController(_request(args), args.journal)).run()
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"codira-installer: {error}", file=sys.stderr)
        return 2
    except InstallationCancelled as error:
        print(
            f"codira-installer: {error}; resume with --resume and --journal",
            file=sys.stderr,
        )
        return 1
    except CalledProcessError as error:
        print(
            f"codira-installer: apply failed: {error}; resume with --resume and --journal",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
