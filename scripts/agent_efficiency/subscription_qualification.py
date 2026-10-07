"""Prove native model tools cannot read the managed login before mounting it."""
# ruff: noqa: EM101, TRY003

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from scripts.agent_efficiency.codex_subscription import (
    SubscriptionTunnel,
    preflight_subscription,
    write_subscription_config,
)
from scripts.agent_efficiency.runner import (
    PROJECT_TEMP_ROOT,
    ContainerAttemptRequest,
    build_container_argv,
    remove_timed_out_container,
    write_proxy_relay,
)


@dataclass(frozen=True)
class SubscriptionRoute:
    """Describe native client admission without carrying decrypted credentials.

    Parameters
    ----------
    runtime, image : str
        Frozen container runtime and exact image digest.
    codex, auth_source : pathlib.Path
        Existing host CLI and managed login file paths.
    model, effort : str
        Exact native model controls.
    """

    runtime: str
    image: str
    codex: Path
    auth_source: Path
    model: str
    effort: str


CANARY_PROGRAM = """from pathlib import Path
from typing import cast
import json, socket
try:
    Path('/codex-state/auth.json').read_bytes()
except PermissionError:
    pass
else:
    raise SystemExit('credential deny rule was not enforced')
Path('/workspace/qualification-write').write_text('public canary')
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise SystemExit('task network was not blocked')
print(json.dumps({'credential_read': 'denied', 'workspace_write': 'allowed', 'network': 'blocked'}))
"""


def qualify_subscription_image(
    runtime: str, image: str, evidence_root: Path, model: str, effort: str
) -> dict[str, object]:
    """Check a public credential canary inside the exact hardened image.

    Parameters
    ----------
    runtime : str
        Supported container runtime.
    image : str
        Exact factory-frozen image digest.
    evidence_root : pathlib.Path
        Durable ignored qualification directory.
    model : str
        Frozen native model identity.
    effort : str
        Reasoning effort used to generate the actual profile.

    Returns
    -------
    dict[str, object]
        Proven credential denial, writable fixture, and blocked tool network.

    Raises
    ------
    ValueError
        If the native tool sandbox or immutable receipt is invalid.
    """
    receipt_path = evidence_root / "subscription-sandbox.json"
    identity = {
        "image": image,
        "model": model,
        "effort": effort,
        "config_builder_sha256": hashlib.sha256(
            inspect.getsource(write_subscription_config).encode()
        ).hexdigest(),
        "qualification_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if receipt_path.exists():
        receipt = cast("dict[str, object]", json.loads(receipt_path.read_text()))
        if receipt.get("identity") != identity or receipt.get("status") != "passed":
            raise ValueError("subscription sandbox receipt differs")
        return receipt
    evidence_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ae-subscription-", dir=PROJECT_TEMP_ROOT
    ) as temporary:
        scratch = Path(temporary)
        fixture, state = scratch / "fixture", scratch / "state"
        fixture.mkdir()
        config = write_subscription_config(state, model, effort, None)
        (state / "home").mkdir()
        (state / "auth.json").write_text('{"canary":"public-nonsecret-qualification"}')
        completed = subprocess.run(
            (
                runtime,
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--cap-add=SETFCAP",
                "--security-opt=no-new-privileges",
                f"--mount=type=bind,src={fixture},dst=/workspace,rw",
                f"--mount=type=bind,src={state},dst=/codex-state,rw",
                f"--mount=type=bind,src={scratch},dst=/temporary,rw",
                "--env=CODEX_HOME=/codex-state",
                "--env=HOME=/codex-state/home",
                "--env=TMPDIR=/temporary",
                "--workdir=/workspace",
                image,
                "codex",
                "--no-daemon",
                "sandbox",
                "-P",
                "benchmark",
                "--",
                "python",
                "-c",
                CANARY_PROGRAM,
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
        config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    for name, value in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        (evidence_root / f"subscription-sandbox.{name}").write_text(value)
    if completed.returncode != 0:
        raise ValueError(
            "native credential sandbox qualification failed; inspect retained trace"
        )
    observations = json.loads(completed.stdout)
    if observations != {
        "credential_read": "denied",
        "workspace_write": "allowed",
        "network": "blocked",
    }:
        raise ValueError("native credential sandbox evidence is incomplete")
    receipt = {
        "identity": identity,
        "status": "passed",
        "config_sha256": config_sha,
        "observations": observations,
    }
    with receipt_path.open("x") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return receipt


def preflight_subscription_in_image(
    route: SubscriptionRoute, evidence_root: Path
) -> dict[str, object]:
    """Read account/model/quota through the actual isolated native transport.

    Parameters
    ----------
    route : SubscriptionRoute
        Frozen native client and existing managed login binding.
    evidence_root : pathlib.Path
        Durable ignored preflight receipt directory.

    Returns
    -------
    dict[str, object]
        Sanitized native account, model and quota admission receipt.

    Raises
    ------
    ValueError
        If credential denial or authenticated native transport is unavailable.
    """
    qualify_subscription_image(
        route.runtime, route.image, evidence_root, route.model, route.effort
    )
    with tempfile.TemporaryDirectory(
        prefix="ae-sub-route-", dir=PROJECT_TEMP_ROOT
    ) as temporary:
        scratch = Path(temporary)
        fixture, state = scratch / "fixture", scratch / "state"
        fixture.mkdir()
        write_subscription_config(state, route.model, route.effort, None)
        (state / "home").mkdir()
        write_proxy_relay(state)
        server = SubscriptionTunnel(str(scratch / "p.sock"))
        request = ContainerAttemptRequest(
            route.runtime,
            route.image,
            fixture,
            state,
            "native preflight",
            60,
            proxy_socket=scratch / "p.sock",
            temporary_root=scratch,
            provider_transport="codex-subscription",
            subscription_auth=route.auth_source,
        )
        argv = build_container_argv(request)
        prefix = argv[: argv.index(route.image) + 1]
        command = (
            prefix[:-1]
            + ("--interactive", prefix[-1])
            + (
                "/bin/sh",
                "-c",
                "python /codex-state/provider_relay.py & relay=$!; codex --no-daemon app-server; status=$?; kill $relay; exit $status",
            )
        )
        try:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            receipt = preflight_subscription(
                route.codex, route.model, route.effort, command=command
            )
        finally:
            remove_timed_out_container(request)
            server.shutdown()
            server.server_close()
    receipt["image"] = route.image
    receipt["transport"] = "network-none container through allowlisted TLS CONNECT"
    with (evidence_root / f"subscription-route-{time.time_ns()}.json").open(
        "x", encoding="utf-8"
    ) as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return receipt
