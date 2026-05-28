#!/usr/bin/env bash
set -u
set -o pipefail

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

MANIFEST="${MANIFEST:-benchmarks/bk-cpp.local.json}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-.artifacts}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUNS="${RUNS:-5}"
WARMUP="${WARMUP:-1}"
CODIRA_DISABLE_THIRD_PARTY_PLUGINS="${CODIRA_DISABLE_THIRD_PARTY_PLUGINS:-1}"
CODIRA_EMBED_BATCH_SIZE="${CODIRA_EMBED_BATCH_SIZE:-128}"
CODIRA_TORCH_NUM_THREADS="${CODIRA_TORCH_NUM_THREADS:-10}"
CODIRA_TORCH_NUM_INTEROP_THREADS="${CODIRA_TORCH_NUM_INTEROP_THREADS:-1}"

run_backend() {
  local backend="$1"
  shift
  local run_id="${STAMP}-bk-cpp-${backend}"
  local run_dir="${ARTIFACT_ROOT}/${run_id}"
  local log_path="${run_dir}/campaign-console.log"
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
  return "${PIPESTATUS[0]}"
}

status=0
run_backend sqlite "$@"
sqlite_status="$?"
if [[ "$sqlite_status" -ne 0 ]]; then
  status="$sqlite_status"
fi

run_backend duckdb "$@"
duckdb_status="$?"
if [[ "$duckdb_status" -ne 0 && "$status" -eq 0 ]]; then
  status="$duckdb_status"
fi

echo "SQLite status: $sqlite_status"
echo "DuckDB status: $duckdb_status"
echo "Artifacts:"
echo "  ${ARTIFACT_ROOT}/${STAMP}-bk-cpp-sqlite"
echo "  ${ARTIFACT_ROOT}/${STAMP}-bk-cpp-duckdb"
exit "$status"
