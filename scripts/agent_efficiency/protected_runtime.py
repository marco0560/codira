"""Run protected behavioral checks in the exact admitted offline image."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

from scripts.agent_efficiency.environment import fixture_environment
from scripts.agent_efficiency.runner import PROJECT_TEMP_ROOT


@dataclass(frozen=True)
class ImageOracleExecutor:
    """Bind grader commands to frozen tools without exposing agent credentials.

    Parameters
    ----------
    runtime, image, fixture_id : str
        Admitted container runtime, image digest and fixture identity.
    result_root : pathlib.Path
        Agent artifact directory mounted read-only for patch application.
    timeout_seconds : int
        Maximum protected command duration.
    """

    runtime: str
    image: str
    fixture_id: str
    result_root: Path
    timeout_seconds: int

    def __call__(
        self, command: Sequence[str], root: Path
    ) -> subprocess.CompletedProcess[bytes]:
        """Execute a protected check with image-bound dependencies and tools.

        Parameters
        ----------
        command : collections.abc.Sequence[str]
            Reviewed non-shell oracle argument vector.
        root : pathlib.Path
            Separate pristine grader workspace, including an applied patch.

        Returns
        -------
        subprocess.CompletedProcess[bytes]
            Complete captured output and actual process arguments.
        """
        # Git applies validated patches on the host; behavioral tools use the image.
        if command[0] == "git":
            return subprocess.run(command, cwd=root, check=False, capture_output=True)
        environment = fixture_environment(root, self.fixture_id)
        with tempfile.TemporaryDirectory(
            prefix="ae-grader-", dir=PROJECT_TEMP_ROOT
        ) as temporary:
            cidfile = f"{temporary}/container.cid"
            argv = (
                self.runtime,
                "run",
                "--rm",
                f"--cidfile={cidfile}",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=512",
                f"--mount=type=bind,src={root.resolve()},dst=/workspace,rw",
                f"--mount=type=bind,src={temporary},dst=/temporary,rw",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,mode=1777,size=128m",
                "--env=TMPDIR=/temporary",
                "--env=UV_CACHE_DIR=/temporary/uv-cache",
                "--env=GOTOOLCHAIN=local",
                "--env=GOPROXY=off",
                "--env=GOSUMDB=off",
                "--env=GOCACHE=/temporary/go-build",
                "--env=GOMODCACHE=/temporary/go-mod",
                "--workdir=/workspace",
                self.image,
                "/bin/sh",
                "-c",
                '"$1" "$2" "$3" >&2 && shift 3 && export PATH="/workspace/.venv/bin:$PATH" && exec "$@"',
                "protected-oracle",
                *environment.prepare_argv,
                *command,
            )
            try:
                return subprocess.run(
                    argv, check=False, capture_output=True, timeout=self.timeout_seconds
                )
            except subprocess.TimeoutExpired as error:
                from pathlib import Path

                if Path(cidfile).is_file():
                    container_id = Path(cidfile).read_text().strip()
                    subprocess.run(
                        (self.runtime, "rm", "--force", container_id),
                        check=False,
                        capture_output=True,
                        timeout=30,
                    )
                return subprocess.CompletedProcess(
                    argv,
                    124,
                    error.stdout or b"",
                    (error.stderr or b"") + b"\nprotected command timed out\n",
                )
