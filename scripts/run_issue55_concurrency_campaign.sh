#!/usr/bin/env bash
# Run the Issue #55 cold full-index concurrency benchmark matrix.
#
# The campaign intentionally excludes CPython: the local Python AST cannot
# parse part of that upstream checkout, including deliberately invalid test
# fixtures. Every benchmark helper failure is fatal after its JSON diagnostic
# has been written.

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
python="$repo_root/.venv/bin/python"
redis_root="${CODIRA_BENCHMARK_REDIS:-/home/marco/Personalia/Progetti/_Third-Party/Test_material_codira/redis}"
run_id="issue-55-concurrency-fixed-$(date -u +%Y%m%dT%H%M%SZ)"
artifact_root="${CODIRA_ISSUE55_ARTIFACT_ROOT:-$repo_root/.artifacts/benchmarks/$run_id}"
readonly measured_runs=10
readonly warmup_runs=2

targets=("$repo_root" "$redis_root")

[[ -x "$python" ]] || { echo "Missing benchmark interpreter: $python" >&2; exit 1; }
for target in "${targets[@]}"; do
  [[ -d "$target" ]] || { echo "Missing benchmark target: $target" >&2; exit 1; }
done

mkdir -p "$artifact_root"/{configs,indexes,samples,warmups}
git -C "$repo_root" rev-parse HEAD > "$artifact_root/git-commit.txt"
git -C "$repo_root" status --short > "$artifact_root/worktree-status.txt"
git -C "$repo_root" diff --binary > "$artifact_root/worktree.patch"

for profile in serial auto process thread; do
  case "$profile" in
    serial) strategy="off"; workers=0 ;;
    auto) strategy="auto"; workers=0 ;;
    process) strategy="process"; workers=4 ;;
    thread) strategy="thread"; workers=4 ;;
  esac

  config="$artifact_root/configs/$profile.toml"
  printf '[embeddings]\nenabled = false\n\n[index.concurrency]\nstrategy = "%s"\nmax_workers = %s\nmin_files = 16\n' \
    "$strategy" "$workers" > "$config"
done

run_sample() {
  local phase="$1" sample="$2" backend="$3" profile="$4" target="$5"
  local label
  label="$(basename "$target")"

  CODIRA_INDEX_BACKEND="$backend" "$python" "$repo_root/scripts/benchmark_index.py" \
    "$target" \
    --full \
    --config-file "$artifact_root/configs/$profile.toml" \
    --output-dir "$artifact_root/indexes/$phase-$backend-$profile-$label-$sample" \
    --output "$artifact_root/$phase/$backend-$profile-$label-$sample.json"
}

# Discarded cold-state warm-ups, then interleaved measured cold full indexes.
for sample in $(seq 1 "$warmup_runs"); do
  for backend in sqlite duckdb; do
    for target in "${targets[@]}"; do
      for profile in serial auto process thread; do
        run_sample warmups "$sample" "$backend" "$profile" "$target"
      done
    done
  done
done

for sample in $(seq 1 "$measured_runs"); do
  for backend in sqlite duckdb; do
    for target in "${targets[@]}"; do
      for profile in serial auto process thread; do
        run_sample samples "$sample" "$backend" "$profile" "$target"
      done
    done
  done
done

printf 'completed_at=%s\nmeasured_samples=%s\nwarmup_samples=%s\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$((measured_runs * ${#targets[@]} * 2 * 4))" \
  "$((warmup_runs * ${#targets[@]} * 2 * 4))" \
  > "$artifact_root/completed.txt"

printf 'Campaign completed successfully: %s\n' "$artifact_root"
