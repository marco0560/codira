#!/usr/bin/env bash
set -u
set -o pipefail

show_help() {
    echo "Usage: $0 [--sqlite-only | --duckdb-only] [manifest.json]"
    echo "  --sqlite-only  Run only the SQLite campaign"
    echo "  --duckdb-only  Run only the DuckDB campaign"
    echo "  -h, --help     Show this help message"
    echo "  Note: If specified, manifest.json must exist."
    echo "        Default: benchmarks/bk-cpp.local.json."
}

sqlite_only=0
duckdb_only=0
manifest_arg=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --sqlite-only)
      sqlite_only=1
      shift
      ;;
    --duckdb-only)
      duckdb_only=1
      shift
      ;;
    -*)
      echo "ERROR: unknown option: $1" >&2
      show_help >&2
      exit 1
      ;;
    *)
      if [[ -n "$manifest_arg" ]]; then
        echo "ERROR: too many positional arguments" >&2
        show_help >&2
        exit 1
      fi
      manifest_arg="$1"
      shift
      ;;
  esac
done

if [[ "$sqlite_only" -eq 1 && "$duckdb_only" -eq 1 ]]; then
  echo "ERROR: --sqlite-only and --duckdb-only are mutually exclusive" >&2
  show_help >&2
  exit 1
fi

if [[ -n "$manifest_arg" && ! -f "$manifest_arg" ]]; then
  echo "ERROR: manifest file does not exist: $manifest_arg" >&2
  show_help >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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

MANIFEST="${MANIFEST:-${manifest_arg:-benchmarks/bk-cpp.local.json}}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-.artifacts}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUNS="${RUNS:-5}"
WARMUP="${WARMUP:-1}"
CODIRA_DISABLE_THIRD_PARTY_PLUGINS="${CODIRA_DISABLE_THIRD_PARTY_PLUGINS:-1}"
CODIRA_EMBED_BATCH_SIZE="${CODIRA_EMBED_BATCH_SIZE:-128}"
CODIRA_TORCH_NUM_THREADS="${CODIRA_TORCH_NUM_THREADS:-10}"
CODIRA_TORCH_NUM_INTEROP_THREADS="${CODIRA_TORCH_NUM_INTEROP_THREADS:-1}"

format_duration() {
  local total="$1"
  local hours=$((total / 3600))
  local minutes=$(((total % 3600) / 60))
  local seconds=$((total % 60))
  if [[ "$hours" -gt 0 ]]; then
    printf '%dh %02dm %02ds' "$hours" "$minutes" "$seconds"
  elif [[ "$minutes" -gt 0 ]]; then
    printf '%dm %02ds' "$minutes" "$seconds"
  else
    printf '%ds' "$seconds"
  fi
}

run_backend() {
  local backend="$1"
  shift
  local run_id="${STAMP}-bk-cpp-${backend}"
  local run_dir="${ARTIFACT_ROOT}/${run_id}"
  local log_path="${run_dir}/campaign-console.log"
  local started_at
  local status
  local elapsed
  started_at="$(date +%s)"
  mkdir -p "$run_dir"
  echo "== ${backend} baseline: ${run_id} =="
  env \
    CODIRA_DISABLE_THIRD_PARTY_PLUGINS="$CODIRA_DISABLE_THIRD_PARTY_PLUGINS" \
    CODIRA_EMBED_BATCH_SIZE="$CODIRA_EMBED_BATCH_SIZE" \
    CODIRA_TORCH_NUM_THREADS="$CODIRA_TORCH_NUM_THREADS" \
    CODIRA_TORCH_NUM_INTEROP_THREADS="$CODIRA_TORCH_NUM_INTEROP_THREADS" \
    CODIRA_INDEX_BACKEND="$backend" \
    "$PYTHON" scripts/benchmark_campaign.py "$MANIFEST" \
      --artifact-root "$ARTIFACT_ROOT" \
      --run-id "$run_id" \
      --runs "$RUNS" \
      --warmup "$WARMUP" \
      --codira "$CODIRA" \
      --python "$PYTHON" \
      --continue-on-error \
      "$@" 2>&1 | tee "$log_path"
  status="${PIPESTATUS[0]}"
  elapsed="$(($(date +%s) - started_at))"
  echo "== ${backend} total: $(format_duration "$elapsed") status=${status} =="
  return "$status"
}

status=0
sqlite_status="skipped"
duckdb_status="skipped"

if [[ "$duckdb_only" -eq 0 ]]; then
  run_backend sqlite
  sqlite_status="$?"
  if [[ "$sqlite_status" -ne 0 ]]; then
    status="$sqlite_status"
  fi
fi

if [[ "$sqlite_only" -eq 0 ]]; then
  run_backend duckdb
  duckdb_status="$?"
  if [[ "$duckdb_status" -ne 0 && "$status" -eq 0 ]]; then
    status="$duckdb_status"
  fi
fi

echo "SQLite status: $sqlite_status"
echo "DuckDB status: $duckdb_status"
echo "Artifacts:"
if [[ "$duckdb_only" -eq 0 ]]; then
  echo "  ${ARTIFACT_ROOT}/${STAMP}-bk-cpp-sqlite"
fi
if [[ "$sqlite_only" -eq 0 ]]; then
  echo "  ${ARTIFACT_ROOT}/${STAMP}-bk-cpp-duckdb"
fi
exit "$status"
