#!/usr/bin/env bash
set -u
set -o pipefail

if [[ "$#" -gt 1 ]] || { [[ "$#" -eq 1 ]] && { [[ "$1" = "-h" ]] || [[ "$1" = "--help" ]]; }; }; then
  echo "Usage: $0 [benchmarks/bk-cpp.local.json]"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MANIFEST_PATH="${1:-benchmarks/bk-cpp.local.json}"
if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "ERROR: manifest not found: $MANIFEST_PATH" >&2
  exit 2
fi

PYTHON="${PYTHON:-}"
CODIRA="${CODIRA:-}"
if [[ -z "$PYTHON" || -z "$CODIRA" ]]; then
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    PYTHON="${PYTHON:-$VIRTUAL_ENV/bin/python}"
    CODIRA="${CODIRA:-$VIRTUAL_ENV/bin/codira}"
  else
    PYTHON="${PYTHON:-$REPO_ROOT/.venv/bin/python}"
    CODIRA="${CODIRA:-$REPO_ROOT/.venv/bin/codira}"
  fi
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python executable not found or not executable: $PYTHON" >&2
  exit 2
fi
if [[ ! -x "$CODIRA" ]]; then
  echo "ERROR: Codira executable not found or not executable: $CODIRA" >&2
  exit 2
fi

STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
MATRIX_ROOT="${MATRIX_ROOT:-.artifacts/issue-057-embedding-matrix/${STAMP}}"
ARTIFACT_ROOT="${MATRIX_ROOT}/campaigns"
CONFIG_ROOT="${MATRIX_ROOT}/configs"
LOG_ROOT="${MATRIX_ROOT}/logs"
METADATA_ROOT="${MATRIX_ROOT}/metadata"
BACKUP_ROOT="${MATRIX_ROOT}/repo-config-backups"

mkdir -p "$ARTIFACT_ROOT" "$CONFIG_ROOT" "$LOG_ROOT" "$METADATA_ROOT" "$BACKUP_ROOT"

cp "$MANIFEST_PATH" "${METADATA_ROOT}/manifest.json"
git rev-parse HEAD > "${METADATA_ROOT}/git-head.txt" 2>/dev/null || true
git status --short > "${METADATA_ROOT}/git-status-short.txt" 2>/dev/null || true
"$CODIRA" config dump > "${METADATA_ROOT}/initial-codira-config.json" 2>&1 || true
env | sort > "${METADATA_ROOT}/environment.txt"

cat > "${CONFIG_ROOT}/immediate-full.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "immediate"
object_types = ["symbol", "documentation"]
max_text_chars = 0
include_paths = []
exclude_paths = []
EOF

cat > "${CONFIG_ROOT}/deferred-full.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "deferred"
object_types = ["symbol", "documentation"]
max_text_chars = 0
include_paths = []
exclude_paths = []
EOF

cat > "${CONFIG_ROOT}/immediate-symbol-only.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "immediate"
object_types = ["symbol"]
max_text_chars = 0
include_paths = []
exclude_paths = []
EOF

cat > "${CONFIG_ROOT}/immediate-documentation-only.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "immediate"
object_types = ["documentation"]
max_text_chars = 0
include_paths = []
exclude_paths = []
EOF

cat > "${CONFIG_ROOT}/immediate-no-embeddings.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "immediate"
object_types = []
max_text_chars = 0
include_paths = []
exclude_paths = []
EOF

cat > "${CONFIG_ROOT}/immediate-capped-docs.toml" <<'EOF'
config_version = 1

[embeddings.indexing]
mode = "immediate"
object_types = ["symbol", "documentation"]
max_text_chars = 2000
include_paths = []
exclude_paths = []
EOF

read_manifest_repos() {
  "$PYTHON" - "$MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
payload = json.loads(manifest.read_text(encoding="utf-8"))
for row in payload["repositories"]:
    print(Path(row["path"]).expanduser().resolve())
PY
}

REPO_LIST="${METADATA_ROOT}/manifest-repositories.txt"
read_manifest_repos > "$REPO_LIST"

backup_repo_configs() {
  local repo
  while IFS= read -r repo; do
    local safe
    safe="$(printf '%s' "$repo" | sed 's#[^A-Za-z0-9._-]#_#g')"
    mkdir -p "${BACKUP_ROOT}/${safe}"

    if [[ -f "${repo}/.codira/config.toml" ]]; then
      cp "${repo}/.codira/config.toml" "${BACKUP_ROOT}/${safe}/config.toml"
      printf 'present\n' > "${BACKUP_ROOT}/${safe}/state"
    else
      printf 'absent\n' > "${BACKUP_ROOT}/${safe}/state"
    fi
  done < "$REPO_LIST"
}

restore_repo_configs() {
  local repo
  while IFS= read -r repo; do
    local safe
    safe="$(printf '%s' "$repo" | sed 's#[^A-Za-z0-9._-]#_#g')"

    if [[ -f "${BACKUP_ROOT}/${safe}/state" ]] && grep -qx 'present' "${BACKUP_ROOT}/${safe}/state"; then
      mkdir -p "${repo}/.codira"
      cp "${BACKUP_ROOT}/${safe}/config.toml" "${repo}/.codira/config.toml"
    else
      rm -f "${repo}/.codira/config.toml"
      rmdir "${repo}/.codira" 2>/dev/null || true
    fi
  done < "$REPO_LIST"
}

apply_repo_config() {
  local config_file="$1"
  local repo
  while IFS= read -r repo; do
    mkdir -p "${repo}/.codira"
    cp "$config_file" "${repo}/.codira/config.toml"
  done < "$REPO_LIST"
}

run_campaign_scenario() {
  local scenario="$1"
  local config_file="$2"
  local started
  local finished
  local status

  echo "== Scenario: ${scenario} =="
  apply_repo_config "$config_file"

  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "$started" > "${METADATA_ROOT}/${scenario}.started-at.txt"

  MANIFEST="$MANIFEST_PATH" \
  ARTIFACT_ROOT="$ARTIFACT_ROOT" \
  STAMP="${STAMP}-${scenario}" \
  PYTHON="$PYTHON" \
  CODIRA="$CODIRA" \
  bash scripts/run_manifest_baseline.sh \
    > "${LOG_ROOT}/${scenario}.log" 2>&1

  status="$?"
  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "$finished" > "${METADATA_ROOT}/${scenario}.finished-at.txt"
  echo "$status" > "${METADATA_ROOT}/${scenario}.status"

  echo "Scenario ${scenario} status=${status}"
  return "$status"
}

run_embeddings_only_after_deferred() {
  local scenario="embeddings-only-after-deferred"
  local started
  local finished
  local status=0
  local backend
  local repo
  local label

  echo "== Scenario: ${scenario} =="

  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "$started" > "${METADATA_ROOT}/${scenario}.started-at.txt"

  for backend in sqlite duckdb; do
    while IFS= read -r repo; do
      label="$(basename "$repo")"
      echo "== ${backend}: ${label} embeddings-only ==" | tee -a "${LOG_ROOT}/${scenario}.log"

      CODIRA_INDEX_BACKEND="$backend" \
      CODIRA_DISABLE_THIRD_PARTY_PLUGINS="${CODIRA_DISABLE_THIRD_PARTY_PLUGINS:-1}" \
      CODIRA_EMBED_BATCH_SIZE="${CODIRA_EMBED_BATCH_SIZE:-128}" \
      CODIRA_TORCH_NUM_THREADS="${CODIRA_TORCH_NUM_THREADS:-10}" \
      CODIRA_TORCH_NUM_INTEROP_THREADS="${CODIRA_TORCH_NUM_INTEROP_THREADS:-1}" \
      "$CODIRA" index \
        --embeddings-only \
        --json \
        --path "$repo" \
        --output-dir "${ARTIFACT_ROOT}/${STAMP}-deferred-full-bk-cpp-${backend}/indexes/$(basename "$repo")" \
        > "${LOG_ROOT}/${scenario}.${backend}.${label}.json" \
        2> "${LOG_ROOT}/${scenario}.${backend}.${label}.stderr"

      rc="$?"
      echo "${backend} ${label} status=${rc}" | tee -a "${LOG_ROOT}/${scenario}.log"
      if [[ "$rc" -ne 0 && "$status" -eq 0 ]]; then
        status="$rc"
      fi
    done < "$REPO_LIST"
  done

  finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "$finished" > "${METADATA_ROOT}/${scenario}.finished-at.txt"
  echo "$status" > "${METADATA_ROOT}/${scenario}.status"

  echo "Scenario ${scenario} status=${status}"
  return "$status"
}

write_index() {
  {
    echo "# Issue #57 embedding benchmark matrix"
    echo
    echo "- Started stamp: \`${STAMP}\`"
    echo "- Manifest: \`${MANIFEST_PATH}\`"
    echo "- Matrix root: \`${MATRIX_ROOT}\`"
    echo
    echo "## Scenarios"
    echo
    for status_file in "${METADATA_ROOT}"/*.status; do
      [[ -f "$status_file" ]] || continue
      scenario="$(basename "$status_file" .status)"
      echo "- \`${scenario}\`: status \`$(cat "$status_file")\`"
    done
    echo
    echo "## Campaign artifact directories"
    echo
    find "$ARTIFACT_ROOT" -maxdepth 1 -mindepth 1 -type d | sort | sed 's#^#- `#; s#$#`#'
    echo
    echo "## Logs"
    echo
    find "$LOG_ROOT" -type f | sort | sed 's#^#- `#; s#$#`#'
    echo
    echo "## Configs"
    echo
    find "$CONFIG_ROOT" -type f | sort | sed 's#^#- `#; s#$#`#'
  } > "${MATRIX_ROOT}/README.md"
}

main() {
  local status=0

  backup_repo_configs
  trap 'restore_repo_configs' EXIT

  run_campaign_scenario "deferred-full" "${CONFIG_ROOT}/deferred-full.toml" || status="$?"
  run_embeddings_only_after_deferred || [[ "$status" -ne 0 ]] || status="$?"
  run_campaign_scenario "immediate-symbol-only" "${CONFIG_ROOT}/immediate-symbol-only.toml" || [[ "$status" -ne 0 ]] || status="$?"
  run_campaign_scenario "immediate-documentation-only" "${CONFIG_ROOT}/immediate-documentation-only.toml" || [[ "$status" -ne 0 ]] || status="$?"
  run_campaign_scenario "immediate-no-embeddings" "${CONFIG_ROOT}/immediate-no-embeddings.toml" || [[ "$status" -ne 0 ]] || status="$?"
  run_campaign_scenario "immediate-capped-docs" "${CONFIG_ROOT}/immediate-capped-docs.toml" || [[ "$status" -ne 0 ]] || status="$?"

  restore_repo_configs
  trap - EXIT

  write_index

  echo
  echo "Matrix root: ${MATRIX_ROOT}"
  echo "Index: ${MATRIX_ROOT}/README.md"
  echo "Status: ${status}"
  exit "$status"
}

main "$@"
