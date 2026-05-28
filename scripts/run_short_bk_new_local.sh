uv run python scripts/benchmark_campaign.py benchmarks/short_bk-new.local.json \
  --run-id "measure-$(date -u +%Y%m%dT%H%M%SZ)" \
  --runs 5 \
  --warmup 1
