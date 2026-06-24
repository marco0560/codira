#!/usr/bin/env bash
set -u
set -o pipefail

show_help() {
  cat <<'EOH'
Usage: scripts/run_final_embedding_model_campaign.sh [options]
       scripts/run_final_embedding_model_campaign.sh --restart-from LABEL
       RESTART_FROM=LABEL scripts/run_final_embedding_model_campaign.sh

Options:
  --baseline PATH          Optional previous embedding matrix artifact directory
                           recorded for analysis metadata.
  --manifest PATH          Repository manifest. Default: benchmarks/uv-backed-repos.local.json
  --model-manifest PATH    Model manifest. Default: benchmarks/embedding-model-candidates.json
  --backend MODE           duckdb, sqlite, or both. Default: duckdb
  --preflight-only         Download and smoke-test models, then stop.
  --restart-from LABEL     Restart from a previously written checkpoint label.
                           The label must be copied from checkpoints/labels.txt.
  -h, --help               Show this help message.

Environment:
  RUNS, WARMUP, ARTIFACT_ROOT, STAMP, PYTHON, CODIRA, and benchmark environment
  variables accepted by scripts/run_manifest_baseline.sh are passed through.

Checkpoint/restart:
  Every successfully completed repository run appends one label to:
    <artifact-root>/<stamp>/checkpoints/labels.txt

  Metadata for those labels is written to:
    <artifact-root>/<stamp>/checkpoints/index.tsv

  To restart after an interruption, copy the last line from labels.txt and run:
    RESTART_FROM='<label>' scripts/run_final_embedding_model_campaign.sh

  Restart mode reloads the original manifest paths, model manifest, backend mode,
  stamp, and artifact root from the checkpoint metadata. Do not pass the original
  options again.
EOH
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*"
}

safe_slug() {
  printf '%s' "$1" | sed 's#[^A-Za-z0-9._-]#_#g'
}

BASELINE_PATH=""
MANIFEST_PATH="benchmarks/uv-backed-repos.local.json"
MODEL_MANIFEST_PATH="benchmarks/embedding-model-candidates.json"
BACKEND_MODE="${BACKEND_MODE:-duckdb}"
PREFLIGHT_ONLY=0
RESTART_FROM="${RESTART_FROM:-}"
EXPLICIT_RESTART=0
CAMPAIGN_OPTION_USED=0

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    RESTART-FROM|restart-from)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: $1 requires a checkpoint label" >&2
        exit 2
      fi
      RESTART_FROM="$2"
      EXPLICIT_RESTART=1
      shift 2
      ;;
    --restart-from)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --restart-from requires a checkpoint label" >&2
        exit 2
      fi
      RESTART_FROM="$2"
      EXPLICIT_RESTART=1
      shift 2
      ;;
    --baseline)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --baseline requires a path" >&2
        exit 2
      fi
      BASELINE_PATH="$2"
      CAMPAIGN_OPTION_USED=1
      shift 2
      ;;
    --manifest)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --manifest requires a path" >&2
        exit 2
      fi
      MANIFEST_PATH="$2"
      CAMPAIGN_OPTION_USED=1
      shift 2
      ;;
    --model-manifest)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --model-manifest requires a path" >&2
        exit 2
      fi
      MODEL_MANIFEST_PATH="$2"
      CAMPAIGN_OPTION_USED=1
      shift 2
      ;;
    --backend)
      if [[ "$#" -lt 2 ]]; then
        echo "ERROR: --backend requires duckdb, sqlite, or both" >&2
        exit 2
      fi
      BACKEND_MODE="$2"
      CAMPAIGN_OPTION_USED=1
      shift 2
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      CAMPAIGN_OPTION_USED=1
      shift
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

if [[ -n "$RESTART_FROM" && "$CAMPAIGN_OPTION_USED" -ne 0 ]]; then
  echo "ERROR: restart mode must be used without the original campaign options" >&2
  echo "Use: RESTART_FROM='<label>' scripts/run_final_embedding_model_campaign.sh" >&2
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

find_checkpoint_root() {
  local label="$1"
  local search_root="${ARTIFACT_ROOT:-.artifacts/final-embedding-model-campaign}"
  local index

  while IFS= read -r index; do
    if awk -F '\t' -v wanted="$label" 'NR > 1 && $1 == wanted { found=1 } END { exit found ? 0 : 1 }' "$index"; then
      dirname "$(dirname "$index")"
      return 0
    fi
  done < <(find "$search_root" -path '*/checkpoints/index.tsv' -type f 2>/dev/null | sort -r)

  return 1
}

RESTART_SEEN=0
if [[ -n "$RESTART_FROM" ]]; then
  CHECKPOINTED_MATRIX_ROOT="$(find_checkpoint_root "$RESTART_FROM" || true)"
  if [[ -z "$CHECKPOINTED_MATRIX_ROOT" ]]; then
    echo "ERROR: checkpoint label not found under ${ARTIFACT_ROOT:-.artifacts/final-embedding-model-campaign}: $RESTART_FROM" >&2
    exit 2
  fi
  if [[ ! -f "${CHECKPOINTED_MATRIX_ROOT}/metadata/run-state.env" ]]; then
    echo "ERROR: checkpoint metadata is incomplete: ${CHECKPOINTED_MATRIX_ROOT}/metadata/run-state.env" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "${CHECKPOINTED_MATRIX_ROOT}/metadata/run-state.env"
  MATRIX_ROOT="$CHECKPOINTED_MATRIX_ROOT"
  CONFIG_ROOT="${MATRIX_ROOT}/configs"
  METADATA_ROOT="${MATRIX_ROOT}/metadata"
  BACKUP_ROOT="${MATRIX_ROOT}/repo-config-backups"
  CAMPAIGN_ROOT="${MATRIX_ROOT}/campaigns"
  LOG_ROOT="${MATRIX_ROOT}/logs"
  CHECKPOINT_ROOT="${MATRIX_ROOT}/checkpoints"
  RESTART_SEEN=0
  log "Restart requested from checkpoint label: ${RESTART_FROM}"
  log "Restart artifacts: ${MATRIX_ROOT}"
else
  STAMP="${STAMP:-$(date +%Y%m%dT%H%M%S%z)}"
  MATRIX_ROOT="${ARTIFACT_ROOT:-.artifacts/final-embedding-model-campaign}/${STAMP}"
  CONFIG_ROOT="${MATRIX_ROOT}/configs"
  METADATA_ROOT="${MATRIX_ROOT}/metadata"
  BACKUP_ROOT="${MATRIX_ROOT}/repo-config-backups"
  CAMPAIGN_ROOT="${MATRIX_ROOT}/campaigns"
  LOG_ROOT="${MATRIX_ROOT}/logs"
  CHECKPOINT_ROOT="${MATRIX_ROOT}/checkpoints"
fi

mkdir -p "$CONFIG_ROOT" "$METADATA_ROOT" "$BACKUP_ROOT" "$CAMPAIGN_ROOT" "$LOG_ROOT" "$CHECKPOINT_ROOT"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: Python executable not found or not executable: $PYTHON" >&2
  exit 2
fi
if [[ ! -x "$CODIRA" ]]; then
  echo "ERROR: Codira executable not found or not executable: $CODIRA" >&2
  exit 2
fi

if [[ -n "$BASELINE_PATH" && ! -e "$BASELINE_PATH" ]]; then
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

LABELS_FILE="${CHECKPOINT_ROOT}/labels.txt"
CHECKPOINT_INDEX="${CHECKPOINT_ROOT}/index.tsv"
if [[ ! -f "$CHECKPOINT_INDEX" ]]; then
  printf 'label\tcompleted_at_local\tmodel_id\tbackend\trepo_index\trepo_label\trepo_path\tstatus\tlog_path\n' > "$CHECKPOINT_INDEX"
fi
touch "$LABELS_FILE"

write_run_metadata() {
  local manifest_abs model_manifest_abs baseline_abs artifact_root_abs
  manifest_abs="$(realpath "$MANIFEST_PATH")"
  model_manifest_abs="$(realpath "$MODEL_MANIFEST_PATH")"
  artifact_root_abs="$(realpath "$(dirname "$MATRIX_ROOT")")"
  if [[ -n "$BASELINE_PATH" ]]; then
    baseline_abs="$(realpath "$BASELINE_PATH")"
    printf '%s\n' "$baseline_abs" > "${METADATA_ROOT}/baseline-path.txt"
  else
    baseline_abs=""
    printf 'not provided\n' > "${METADATA_ROOT}/baseline-path.txt"
  fi

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

  {
    printf 'BASELINE_PATH=%q\n' "$baseline_abs"
    printf 'MANIFEST_PATH=%q\n' "$manifest_abs"
    printf 'MODEL_MANIFEST_PATH=%q\n' "$model_manifest_abs"
    printf 'BACKEND_MODE=%q\n' "$BACKEND_MODE"
    printf 'STAMP=%q\n' "$STAMP"
    printf 'ARTIFACT_ROOT=%q\n' "$artifact_root_abs"
    printf 'PYTHON=%q\n' "$PYTHON"
    printf 'CODIRA=%q\n' "$CODIRA"
  } > "${METADATA_ROOT}/run-state.env"
}

if [[ -z "$RESTART_FROM" ]]; then
  write_run_metadata
else
  log "Using existing checkpoint labels file: ${LABELS_FILE}"
  log "Using existing checkpoint index: ${CHECKPOINT_INDEX}"
fi

log "Campaign artifacts: ${MATRIX_ROOT}"
log "Checkpoint labels: ${LABELS_FILE}"
log "Checkpoint metadata: ${CHECKPOINT_INDEX}"

if [[ -z "$RESTART_FROM" ]]; then
  log "Preflight started: download and smoke-test embedding models"
  "$PYTHON" scripts/download_embedding_model.py \
    --manifest "$MODEL_MANIFEST_PATH" \
    > "${LOG_ROOT}/model-download-preflight.log" 2>&1
  preflight_status="$?"
  log "Preflight completed status=${preflight_status}; log=${LOG_ROOT}/model-download-preflight.log"
  if [[ "$preflight_status" -ne 0 ]]; then
    exit "$preflight_status"
  fi
else
  log "Preflight skipped on restart"
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  log "Preflight artifacts: ${MATRIX_ROOT}"
  exit 0
fi

read_manifest_repos() {
  "$PYTHON" - "$MANIFEST_PATH" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for index, row in enumerate(payload["repositories"], start=1):
    label = row.get("label") or Path(row["path"]).name
    print(f"{index}\t{label}\t{Path(row['path']).expanduser().resolve()}")
PY
}

write_single_repo_manifest() {
  local repo_index="$1"
  local output_path="$2"
  "$PYTHON" - "$MANIFEST_PATH" "$repo_index" "$output_path" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
repo_index = int(sys.argv[2])
output_path = Path(sys.argv[3])
payload = json.loads(manifest.read_text(encoding="utf-8"))
repositories = payload["repositories"]
if repo_index < 1 or repo_index > len(repositories):
    raise SystemExit(f"repository index out of range: {repo_index}")
payload["repositories"] = [repositories[repo_index - 1]]
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

REPO_TABLE="${METADATA_ROOT}/manifest-repositories.tsv"
REPO_LIST="${METADATA_ROOT}/manifest-repositories.txt"
if [[ -z "$RESTART_FROM" || ! -f "$REPO_TABLE" ]]; then
  read_manifest_repos > "$REPO_TABLE"
fi
cut -f3 "$REPO_TABLE" > "$REPO_LIST"

backup_repo_configs() {
  local repo
  while IFS= read -r repo; do
    local safe
    safe="$(safe_slug "$repo")"
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
    safe="$(safe_slug "$repo")"
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
  "$PYTHON" - "$MODEL_MANIFEST_PATH" "$CONFIG_ROOT" "$BACKEND_MODE" <<'PY'
import json
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
config_root = Path(sys.argv[2])
backend_mode = sys.argv[3]
payload = json.loads(manifest.read_text(encoding="utf-8"))
backend_name = "duckdb" if backend_mode in {"duckdb", "both"} else "sqlite"
vector_store_name = backend_name

for entry in payload["models"]:
    config = entry.get("config", {})
    lines = [
        "config_version = 1",
        "",
        "[backend]",
        f'name = "{backend_name}"',
        "",
        "[plugins]",
        "disable_third_party = false",
        "disabled_analyzers = []",
        "",
        "[embeddings]",
        "enabled = true",
        f'engine = "{entry["engine"]}"',
        f'vector_store = "{vector_store_name}"',
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
        f"max_tokens = {int(config.get('max_tokens', 512))}",
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

append_checkpoint() {
  local label="$1"
  local model_id="$2"
  local repo_index="$3"
  local repo_label="$4"
  local repo_path="$5"
  local status="$6"
  local log_path="$7"
  local completed_at
  completed_at="$(date '+%Y-%m-%d %H:%M:%S %z')"
  printf '%s\n' "$label" >> "$LABELS_FILE"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$label" "$completed_at" "$model_id" "$BACKEND_MODE" "$repo_index" "$repo_label" "$repo_path" "$status" "$log_path" \
    >> "$CHECKPOINT_INDEX"
  log "Checkpoint written: ${label}"
}

checkpoint_seen() {
  local label="$1"
  awk -F '\t' -v wanted="$label" 'NR > 1 && $1 == wanted { found=1 } END { exit found ? 0 : 1 }' "$CHECKPOINT_INDEX"
}

run_repo_campaign() {
  local model_id="$1"
  local repo_index="$2"
  local repo_label="$3"
  local repo_path="$4"
  local config_file="${CONFIG_ROOT}/${model_id}.toml"
  local repo_slug model_slug label repo_manifest log_path repo_stamp status
  local backend_args=()

  case "$BACKEND_MODE" in
    duckdb) backend_args=(--duckdb-only) ;;
    sqlite) backend_args=(--sqlite-only) ;;
    both) backend_args=() ;;
  esac

  repo_slug="$(safe_slug "${repo_index}-${repo_label}")"
  model_slug="$(safe_slug "$model_id")"
  label="ckpt_${STAMP}_${model_slug}_${BACKEND_MODE}_${repo_slug}"

  if [[ -n "$RESTART_FROM" && "$RESTART_SEEN" -eq 0 ]]; then
    if [[ "$label" == "$RESTART_FROM" ]]; then
      RESTART_SEEN=1
      log "Restart point reached; skipping completed checkpoint: ${label}"
    else
      log "Skipping before restart point: model=${model_id} repo=${repo_label}"
    fi
    return 0
  fi

  if checkpoint_seen "$label"; then
    log "Skipping already checkpointed phase: ${label}"
    return 0
  fi

  repo_manifest="${METADATA_ROOT}/single-repo-manifests/${repo_slug}.json"
  log_path="${LOG_ROOT}/${model_slug}-${repo_slug}.log"
  repo_stamp="${STAMP}-${model_slug}-${repo_slug}"

  write_single_repo_manifest "$repo_index" "$repo_manifest"

  log "Phase started: model=${model_id} backend=${BACKEND_MODE} repo=${repo_label} path=${repo_path}"
  apply_repo_config "$config_file"

  ARTIFACT_ROOT="$CAMPAIGN_ROOT" \
  STAMP="$repo_stamp" \
  PYTHON="$PYTHON" \
  CODIRA="$CODIRA" \
  bash scripts/run_manifest_baseline.sh "${backend_args[@]}" "$repo_manifest" \
    > "$log_path" 2>&1
  status="$?"
  printf '%s\n' "$status" > "${METADATA_ROOT}/${model_slug}-${repo_slug}.status"
  log "Phase completed: model=${model_id} repo=${repo_label} status=${status}; log=${log_path}"

  if [[ "$status" -eq 0 ]]; then
    append_checkpoint "$label" "$model_id" "$repo_index" "$repo_label" "$repo_path" "$status" "$log_path"
  else
    log "No checkpoint written for failed phase: model=${model_id} repo=${repo_label} status=${status}"
  fi

  return "$status"
}

status=0
if [[ -z "$RESTART_FROM" ]]; then
  backup_repo_configs
else
  log "Repository config backup from original run will be reused"
fi
trap restore_repo_configs EXIT

MODEL_IDS="${METADATA_ROOT}/model-ids.txt"
if [[ -z "$RESTART_FROM" || ! -f "$MODEL_IDS" ]]; then
  write_model_configs > "$MODEL_IDS"
fi

while IFS= read -r model_id; do
  [[ -z "$model_id" ]] && continue
  log "Model campaign started: ${model_id} backend=${BACKEND_MODE}"
  while IFS=$'\t' read -r repo_index repo_label repo_path; do
    [[ -z "$repo_index" ]] && continue
    run_repo_campaign "$model_id" "$repo_index" "$repo_label" "$repo_path"
    rc="$?"
    if [[ "$rc" -ne 0 && "$status" -eq 0 ]]; then
      status="$rc"
    fi
  done < "$REPO_TABLE"
  log "Model campaign completed: ${model_id} current_status=${status}"
done < "$MODEL_IDS"

if [[ -n "$RESTART_FROM" && "$RESTART_SEEN" -eq 0 ]]; then
  echo "ERROR: restart label was not reached during traversal: $RESTART_FROM" >&2
  exit 2
fi

{
  echo "# Final embedding model campaign"
  echo
  echo "- Baseline: $(cat "${METADATA_ROOT}/baseline-path.txt")"
  echo "- Repository manifest: ${MANIFEST_PATH}"
  echo "- Model manifest: ${MODEL_MANIFEST_PATH}"
  echo "- Backend mode: ${BACKEND_MODE}"
  echo "- Checkpoint labels: ${LABELS_FILE}"
  echo "- Checkpoint metadata: ${CHECKPOINT_INDEX}"
  echo
  echo "Artifacts are under \`${MATRIX_ROOT}\`."
  echo
  echo "Restart from the last completed phase with:"
  echo
  echo '```bash'
  echo "RESTART_FROM='$(tail -n 1 "$LABELS_FILE" 2>/dev/null || true)' scripts/run_final_embedding_model_campaign.sh"
  echo '```'
} > "${MATRIX_ROOT}/README.md"

log "Final campaign artifacts: ${MATRIX_ROOT}"
log "Checkpoint labels: ${LABELS_FILE}"
exit "$status"
