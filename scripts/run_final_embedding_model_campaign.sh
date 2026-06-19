#!/usr/bin/env bash
set -u
set -o pipefail

show_help() {
  cat <<'EOF'
Usage: scripts/run_final_embedding_model_campaign.sh --baseline PATH [options]

Options:
  --baseline PATH          Previous embedding matrix artifact directory.
  --manifest PATH          Repository manifest. Default: benchmarks/uv-backed-repos.local.json
  --model-manifest PATH    Model manifest. Default: benchmarks/embedding-model-candidates.json
  --backend MODE           duckdb, sqlite, or both. Default: duckdb
  -h, --help               Show this help message.

Environment:
  RUNS, WARMUP, ARTIFACT_ROOT, STAMP, PYTHON, CODIRA, and benchmark environment
  variables accepted by scripts/run_manifest_baseline.sh are passed through.
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BASELINE_PATH=""
MANIFEST_PATH="benchmarks/uv-backed-repos.local.json"
MODEL_MANIFEST_PATH="benchmarks/embedding-model-candidates.json"
BACKEND_MODE="${BACKEND_MODE:-duckdb}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --baseline)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --baseline requires a path" >&2
        exit 2
      fi
      BASELINE_PATH="$2"
      shift 2
      ;;
    --manifest)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --manifest requires a path" >&2
        exit 2
      fi
      MANIFEST_PATH="$2"
      shift 2
      ;;
    --model-manifest)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --model-manifest requires a path" >&2
        exit 2
      fi
      MODEL_MANIFEST_PATH="$2"
      shift 2
      ;;
    --backend)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --backend requires duckdb, sqlite, or both" >&2
        exit 2
      fi
      BACKEND_MODE="$2"
      shift 2
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      show_help >&2
      exit 2
      ;;
  esac
done

if [[ -z "$BASELINE_PATH" ]]; then
  echo "ERROR: --baseline is required" >&2
  show_help >&2
  exit 2
fi
if [[ ! -e "$BASELINE_PATH" ]]; then
  echo "ERROR: baseline path does not exist: $BASELINE_PATH" >&2
  exit 2
fi
if [[ ! -f "$MANIFEST_PATH" ]]; then
  echo "ERROR: repository manifest not found: $MANIFEST_PATH" >&2
  exit 2
fi
if [[ ! -f "$MODEL_MANIFEST_PATH" ]]; then
  echo "ERROR: model manifest not found: $MODEL_MANIFEST_PATH" >&2
  exit 2
fi
case "$BACKEND_MODE" in
  duckdb|sqlite|both) ;;
  *)
    echo "ERROR: --backend must be duckdb, sqlite, or both" >&2
    exit 2
    ;;
esac

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
MATRIX_ROOT="${ARTIFACT_ROOT:-.artifacts/final-embedding-model-campaign}/${STAMP}"
CONFIG_ROOT="${MATRIX_ROOT}/configs"
METADATA_ROOT="${MATRIX_ROOT}/metadata"
BACKUP_ROOT="${MATRIX_ROOT}/repo-config-backups"
CAMPAIGN_ROOT="${MATRIX_ROOT}/campaigns"
LOG_ROOT="${MATRIX_ROOT}/logs"

mkdir -p "$CONFIG_ROOT" "$METADATA_ROOT" "$BACKUP_ROOT" "$CAMPAIGN_ROOT" "$LOG_ROOT"

realpath "$BASELINE_PATH" > "${METADATA_ROOT}/baseline-path.txt"
cp "$MANIFEST_PATH" "${METADATA_ROOT}/repository-manifest.json"
cp "$MODEL_MANIFEST_PATH" "${METADATA_ROOT}/model-manifest.json"
git rev-parse HEAD > "${METADATA_ROOT}/git-head.txt" 2>/dev/null || true
git status --short > "${METADATA_ROOT}/git-status-short.txt" 2>/dev/null || true
{
  printf 'ARTIFACT_ROOT=%s\n' "${ARTIFACT_ROOT:-}"
  printf 'BACKEND_MODE=%s\n' "$BACKEND_MODE"
  printf 'CODIRA=%s\n' "$CODIRA"
  printf 'CODIRA_DISABLE_THIRD_PARTY_PLUGINS=%s\n' "${CODIRA_DISABLE_THIRD_PARTY_PLUGINS:-}"
  printf 'CODIRA_EMBED_BATCH_SIZE=%s\n' "${CODIRA_EMBED_BATCH_SIZE:-}"
  printf 'CODIRA_TORCH_NUM_INTEROP_THREADS=%s\n' "${CODIRA_TORCH_NUM_INTEROP_THREADS:-}"
  printf 'CODIRA_TORCH_NUM_THREADS=%s\n' "${CODIRA_TORCH_NUM_THREADS:-}"
  printf 'PYTHON=%s\n' "$PYTHON"
  printf 'RUNS=%s\n' "${RUNS:-}"
  printf 'STAMP=%s\n' "$STAMP"
  printf 'WARMUP=%s\n' "${WARMUP:-}"
} > "${METADATA_ROOT}/environment.txt"

read_manifest_repos() {
  "$PYTHON" - "$MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
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

write_model_configs() {
  "$PYTHON" - "$MODEL_MANIFEST_PATH" "$CONFIG_ROOT" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
config_root = Path(sys.argv[2])
payload = json.loads(manifest.read_text(encoding="utf-8"))

for entry in payload["models"]:
    config = entry.get("config", {})
    lines = [
        "config_version = 1",
        "",
        "[backend]",
        'name = "duckdb"',
        "",
        "[plugins]",
        "disable_third_party = false",
        "disabled_analyzers = []",
        "",
        "[embeddings]",
        "enabled = true",
        f'engine = "{entry["engine"]}"',
        'vector_store = "duckdb"',
        f'model = "{entry["model"]}"',
        f'version = "{entry["version"]}"',
        f"dimension = {int(entry['dimension'])}",
        'device = "cpu"',
        "batch_size = 32",
        "torch_num_threads = 0",
        "torch_num_interop_threads = 0",
        "",
        "[embeddings.gpu]",
        "device_id = 0",
        "memory_limit_mb = 0",
        "",
        "[embeddings.indexing]",
        'mode = "immediate"',
        'object_types = ["symbol", "documentation"]',
        "max_text_chars = 0",
        "include_paths = []",
        "exclude_paths = []",
        "",
        "[plugins.embedding-sentence-transformers]",
        "enabled = true",
        'precision = "float32"',
        "trust_remote_code = false",
        "",
        "[plugins.embedding-onnx]",
        "enabled = true",
        f'precision = "{entry.get("precision", "float32")}"',
        f'model_path = "{config.get("model_path", "")}"',
        f'tokenizer_path = "{config.get("tokenizer_path", "")}"',
        f'provider = "{config.get("provider", "CPUExecutionProvider")}"',
        "normalize = true",
        "intra_op_num_threads = 0",
        "inter_op_num_threads = 0",
        "",
        "[plugins.vector-store-sqlite]",
        "enabled = true",
        "",
        "[plugins.vector-store-duckdb]",
        "enabled = true",
        "",
    ]
    if "trust_remote_code" in config:
        rendered = str(config["trust_remote_code"]).lower()
        lines[lines.index("trust_remote_code = false")] = f"trust_remote_code = {rendered}"
    output = config_root / f"{entry['id']}.toml"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(entry["id"])
PY
}

apply_repo_config() {
  local config_file="$1"
  local repo
  while IFS= read -r repo; do
    mkdir -p "${repo}/.codira"
    cp "$config_file" "${repo}/.codira/config.toml"
  done < "$REPO_LIST"
}

run_model_campaign() {
  local model_id="$1"
  local config_file="${CONFIG_ROOT}/${model_id}.toml"
  local backend_args=()
  local status

  case "$BACKEND_MODE" in
    duckdb) backend_args=(--duckdb-only) ;;
    sqlite) backend_args=(--sqlite-only) ;;
    both) backend_args=() ;;
  esac

  echo "== Model campaign: ${model_id} backend=${BACKEND_MODE} =="
  apply_repo_config "$config_file"

  ARTIFACT_ROOT="$CAMPAIGN_ROOT" \
  STAMP="${STAMP}-${model_id}" \
  PYTHON="$PYTHON" \
  CODIRA="$CODIRA" \
  bash scripts/run_manifest_baseline.sh "${backend_args[@]}" "$MANIFEST_PATH" \
    > "${LOG_ROOT}/${model_id}.log" 2>&1
  status="$?"
  echo "$status" > "${METADATA_ROOT}/${model_id}.status"
  echo "Model ${model_id} status=${status}"
  return "$status"
}

status=0
backup_repo_configs
trap restore_repo_configs EXIT

MODEL_IDS="${METADATA_ROOT}/model-ids.txt"
write_model_configs > "$MODEL_IDS"

while IFS= read -r model_id; do
  run_model_campaign "$model_id"
  rc="$?"
  if [[ "$rc" -ne 0 && "$status" -eq 0 ]]; then
    status="$rc"
  fi
done < "$MODEL_IDS"

{
  echo "# Final embedding model campaign"
  echo
  echo "- Baseline: $(cat "${METADATA_ROOT}/baseline-path.txt")"
  echo "- Repository manifest: ${MANIFEST_PATH}"
  echo "- Model manifest: ${MODEL_MANIFEST_PATH}"
  echo "- Backend mode: ${BACKEND_MODE}"
  echo
  echo "Artifacts are under \`${MATRIX_ROOT}\`."
} > "${MATRIX_ROOT}/README.md"

echo "Final campaign artifacts: ${MATRIX_ROOT}"
exit "$status"
