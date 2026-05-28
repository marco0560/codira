uv run CODIRA_INDEX_BACKEND=sqlite python scripts/benchmark_campaign.py benchmarks/short_bk-new.local.json \
  --run-id "measure-sqlite-$(date -u +%Y%m%dT%H%M%SZ)" \
  --runs 5 \
  --warmup 1

uv run CODIRA_INDEX_BACKEND=duckdb python scripts/benchmark_campaign.py benchmarks/short_bk-new.local.json \
  --run-id "measure-duckdb-$(date -u +%Y%m%dT%H%M%SZ)" \
  --runs 5 \
  --warmup 1
