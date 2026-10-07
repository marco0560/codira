#!/usr/bin/env bash
# Prepare and verify a dedicated Issue #53 Phase 0 execution host.
#
# This helper never starts a Codex turn, decrypts a secret, or supplies a
# credential to a benchmark agent. --install-codex and --pull-image are explicit
# opt-ins because they change the host and may use the network.

set -euo pipefail

readonly REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEFAULT_RUNTIME="docker"

usage() {
    cat <<'EOF'
Usage:
  scripts/prepare_agent_efficiency_phase0_host.sh \
    --codex-version VERSION \
    --image IMAGE@sha256:DIGEST \
    --auth-boundary provider-proxy|workload-identity \
    [--runtime docker|podman] [--codex PATH] [--install-codex] [--pull-image]

Required inputs:
  --codex-version VERSION       Exact Codex CLI version to pin.
  --image IMAGE@sha256:DIGEST   Exact, selected benchmark image digest.
  --auth-boundary MODE          runner-side provider-proxy or workload-identity.

Optional actions:
  --install-codex               Install @openai/codex@VERSION with npm.
  --pull-image                  Pull the supplied digest-pinned image.

The helper rejects CODEX_API_KEY and OPENAI_API_KEY in its environment. It does
not install Docker/Podman because that is host- and privilege-specific. It also
does not authenticate Codex or run a paid conformance probe.
EOF
}

fail() {
    printf 'Phase 0 host preparation failed: %s\n' "$*" >&2
    exit 2
}

require_value() {
    local option="$1"
    local value="$2"
    [[ -n "$value" ]] || fail "$option requires a value"
}

codex_version=""
codex_binary="codex"
runtime="$DEFAULT_RUNTIME"
image=""
auth_boundary=""
install_codex=false
pull_image=false

while (($# > 0)); do
    case "$1" in
        --codex-version)
            (($# >= 2)) || fail "--codex-version requires a value"
            codex_version="$2"
            shift 2
            ;;
        --codex)
            (($# >= 2)) || fail "--codex requires a value"
            codex_binary="$2"
            shift 2
            ;;
        --runtime)
            (($# >= 2)) || fail "--runtime requires a value"
            runtime="$2"
            shift 2
            ;;
        --image)
            (($# >= 2)) || fail "--image requires a value"
            image="$2"
            shift 2
            ;;
        --auth-boundary)
            (($# >= 2)) || fail "--auth-boundary requires a value"
            auth_boundary="$2"
            shift 2
            ;;
        --install-codex)
            install_codex=true
            shift
            ;;
        --pull-image)
            pull_image=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            fail "unknown option: $1"
            ;;
    esac
done

require_value "--codex-version" "$codex_version"
require_value "--image" "$image"
require_value "--auth-boundary" "$auth_boundary"

[[ "$codex_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([-.][0-9A-Za-z.]+)?$ ]] \
    || fail "--codex-version must be a concrete semantic version"
[[ "$image" =~ @sha256:[0-9a-f]{64}$ ]] \
    || fail "--image must use an exact lowercase sha256 digest"
case "$runtime" in
    docker|podman) ;;
    *) fail "--runtime must be docker or podman" ;;
esac
case "$auth_boundary" in
    provider-proxy|workload-identity) ;;
    *) fail "--auth-boundary must be provider-proxy or workload-identity" ;;
esac

[[ -z "${CODEX_API_KEY:-}" ]] || fail "CODEX_API_KEY must not enter this helper"
[[ -z "${OPENAI_API_KEY:-}" ]] || fail "OPENAI_API_KEY must not enter this helper"

if "$install_codex"; then
    command -v npm >/dev/null 2>&1 || fail "npm is required for --install-codex"
    npm install --global "@openai/codex@${codex_version}"
fi

command -v "$codex_binary" >/dev/null 2>&1 \
    || fail "Codex executable not found: $codex_binary"
command -v "$runtime" >/dev/null 2>&1 \
    || fail "container runtime not found: $runtime"

actual_codex_version="$("$codex_binary" --version)"
[[ "$actual_codex_version" == *"$codex_version"* ]] \
    || fail "Codex version does not contain requested $codex_version: $actual_codex_version"

if "$pull_image"; then
    "$runtime" pull "$image"
fi
"$runtime" image inspect "$image" >/dev/null 2>&1 \
    || fail "digest-pinned image is unavailable locally: $image"

state_root="$(mktemp -d "${TMPDIR:-/tmp}/codira-agent-efficiency-phase0.XXXXXX")"
cleanup() {
    rmdir "$state_root" 2>/dev/null || true
}
trap cleanup EXIT

printf '%s\n' "Authentication boundary recorded: $auth_boundary"
printf '%s\n' "Codex version recorded: $actual_codex_version"
printf '%s\n' "Container runtime recorded: $("$runtime" --version | head -n 1)"
printf '%s\n' "Image digest recorded: $image"

cd "$REPOSITORY_ROOT"
uv run python scripts/check_agent_efficiency_environment.py \
    --codex "$(command -v "$codex_binary")" \
    --container-runtime "$runtime" \
    --image "$image" \
    --state-root "$state_root"

printf '%s\n' "Non-billed host preflight passed."
