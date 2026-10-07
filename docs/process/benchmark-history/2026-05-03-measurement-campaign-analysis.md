# Measurement Campaign Analysis

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-05-03-measurement-campaign-analysis.md`
(SHA-256 `e458ed029f399a2114af15020c5f446430aee630d3ed4a249671c8ad2643301e`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/20260501T111958Z` | unavailable historical path |
| `.artifacts/20260502T172501Z` | unavailable historical path |


Date: 2026-05-03

Hardware snapshot for this analysis:

- Host kernel: `Linux verona 6.18.26-gentoo-dist #1 SMP PREEMPT_DYNAMIC Thu Apr 30 21:44:48 -00 2026 x86_64`
- OS: `Gentoo Linux 2.18`
- CPU: `Intel(R) Core(TM) i7-8700K CPU @ 3.70GHz`
- CPU topology: `1 socket`, `6 physical cores`, `12 logical CPUs`, max reported frequency `4.70 GHz`
- Memory: `46 GiB` RAM total, `83 GiB` swap total
- GPU present: `NVIDIA GeForce GTX 1050 (GP107)`
- GPU driver/runtime status during analysis update: `nvidia-smi` was not usable because it could not communicate with the NVIDIA driver
- Embedding device configuration at analysis-update time: `CODIRA_EMBED_DEVICE` was unset
- Embedding device selection in code: `src/codira/semantic/embeddings.py::_configured_embedding_device()` defaults to `cpu` when `CODIRA_EMBED_DEVICE` is unset
- Embeddings in this environment should therefore be treated as CPU-backed unless that environment variable is explicitly set and the NVIDIA runtime is functioning

Compared campaigns:

- `.artifacts/20260502T172501Z`
- `.artifacts/20260501T111958Z`

Comparison basis:

- identical benchmark matrix across both campaigns
- previous campaign metadata: `codira 1.21.0`, commit `eaf1fd387a439f0beb0cf21b61c5ee590c1ec586`
- latest campaign metadata: `codira 1.21.7`, commit `2a5cbaec12ab3d9874257e8f8c34622120828c8f`

Measurement note:

- In `*-index-phases.json`, `timings.total` is wall-clock for one index pass.
- `timings.embeddings` is cumulative diagnostic time across repeated embedding hooks and is not additive to `total`.
- This behavior is defined in `scripts/benchmark_index.py`.

## Objective 1

Overall result:

- 41 of 51 hyperfine measurements improved
- 10 of 51 regressed
- no regression is strong enough to outweigh the campaign-wide gains

Aggregate by command family:

| Family | Previous | Latest | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `index --full` | 3350.636s | 3228.280s | -122.356s | -3.65% |
| warm `index` | 26.115s | 20.635s | -5.481s | -20.99% |
| `ctx` | 151.807s | 114.001s | -37.806s | -24.90% |
| `sym` | 0.900s | 0.402s | -0.498s | -55.36% |

Largest repository-level wins by summed hyperfine means:

| Repository | Previous | Latest | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cpython` | 1102.577s | 1023.966s | -78.611s | -7.13% |
| `large-postgres` | 721.333s | 691.771s | -29.562s | -4.10% |
| `large-texlive` | 1256.524s | 1230.292s | -26.232s | -2.09% |
| `large-cldr-json` | 40.509s | 22.308s | -18.201s | -44.93% |
| `small-codira` | 55.393s | 51.918s | -3.476s | -6.27% |

Largest individual wins:

| Benchmark | Previous | Latest | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cldr-json ctx` | 19.629s | 10.567s | -9.062s | -46.17% |
| `large-postgres ctx` | 18.048s | 9.260s | -8.788s | -48.69% |
| `large-texlive ctx` | 19.528s | 12.968s | -6.560s | -33.59% |
| `large-cldr-json warm index` | 7.210s | 2.721s | -4.489s | -62.26% |
| `large-cldr-json full index` | 13.670s | 9.020s | -4.650s | -34.02% |
| `small-codira ctx` | 7.664s | 5.734s | -1.930s | -25.18% |
| `small-codira sym` | 0.689s | 0.204s | -0.485s | -70.42% |

Largest phase-level wins from `*-index-phases.json`:

| Phase | Previous | Latest | Absolute delta | Delta % |
|---|---:|---:|---:|---:|
| `large-cldr-json total` | 14.009s | 8.973s | -5.036s | -35.95% |
| `large-cpython total` | 973.894s | 938.897s | -34.997s | -3.59% |
| `large-postgres total` | 693.036s | 670.451s | -22.585s | -3.26% |
| `large-texlive total` | 1210.746s | 1194.427s | -16.319s | -1.35% |

Most likely measured cause of the strongest win:

- The JSON analyzer now gates full parses behind `_sniff_json_path_candidate()` before `_load_json_mapping()`.
- Changed code is in `packages/codira-analyzer-json/src/codira_analyzer_json/__init__.py`.
- In `large-cldr-json-ctx.prof`, `supports_path` dropped from `13.479s` to `5.310s`.
- The old `_load_json_mapping` hotspot disappeared from the top profile entries.

Regressions:

| Benchmark | Previous | Latest | Absolute delta | Delta % | Signal |
|---|---:|---:|---:|---:|---:|
| `small-tree-sitter-c full index` | 13.805s | 14.080s | +0.275s | +1.99% | 0.41 sigma |
| `small-requests full index` | 13.187s | 13.348s | +0.161s | +1.22% | 0.29 sigma |
| `small-tree-sitter-python full index` | 9.941s | 10.079s | +0.138s | +1.39% | 0.30 sigma |
| `medium-redis warm index` | 1.048s | 1.173s | +0.125s | +11.88% | 0.80 sigma |
| `small-codira warm index` | 0.355s | 0.406s | +0.051s | +14.50% | 0.81 sigma |
| `small-codira emb` | 5.693s | 5.733s | +0.041s | +0.71% | 0.16 sigma |
| `small-codira caps` | 0.161s | 0.176s | +0.015s | +9.59% | 1.42 sigma |
| `small-codira plugins` | 0.172s | 0.178s | +0.006s | +3.67% | 1.08 sigma |
| `small-tree-sitter-python warm index` | 0.237s | 0.243s | +0.006s | +2.44% | 0.52 sigma |
| `small-codira help` | 0.146s | 0.148s | +0.003s | +1.94% | 0.22 sigma |

Conclusion for Objective 1:

- The campaign shows broad improvement.
- The only visible regressions are small and mostly below run-to-run noise.
- There is no significant regression that changes the overall direction.

## Objective 2

Hotspots in importance order:

1. Embedding inference and embedding persistence
    - `src/codira/semantic/embeddings.py::embed_texts`
    - `src/codira/sqlite_backend_support.py::_flush_embedding_rows`
    - `large-texlive-index.prof`: `1235.061s` and `1239.295s`
    - `large-cpython-index.prof`: `952.618s` and `959.110s`
    - `large-postgres-index.prof`: `686.910s` and `683.108s`
    - Full indexing remains overwhelmingly embedding-bound.

2. ML runtime execution and cold-start cost
    - dominant callees under the embedding path are in `sentence_transformers`, `transformers`, and `torch`
    - small-repo `ctx` still shows substantial Torch/Transformers import and execution cost

3. SQLite embedding retrieval and Python-side similarity scoring
    - `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py::embedding_candidates`
    - `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py::rebuild_derived_indexes`
    - `_dot_similarity` remains heavy on large `ctx` runs
    - `large-cpython-ctx.prof`: `embedding_candidates 9.410s`, `rebuild_derived_indexes 9.767s`, `_dot_similarity 7.448s`

4. Context reference expansion and project-wide rescans
    - `src/codira/query/context.py::_collect_reference_rows`
    - `src/codira/query/context.py::_expand_and_collect_references`
    - `src/codira/scanner.py::iter_project_files`
    - `large-cldr-json-ctx.prof`: `iter_project_files 7.509s`, `_collect_reference_rows 3.724s`, `_expand_and_collect_references 3.732s`

5. JSON analyzer path classification on JSON-heavy trees
    - `packages/codira-analyzer-json/src/codira_analyzer_json/__init__.py::_sniff_json_path_candidate`
    - `packages/codira-analyzer-json/src/codira_analyzer_json/__init__.py::supports_path`
    - `large-cldr-json-ctx.prof`: `supports_path 5.310s`, `_sniff_json_path_candidate 4.417s`
    - This area improved sharply but remains sensitive on large JSON corpora.

## Objective 3

Assessment on current hardware:

- There is still significant performance headroom.
- The data does not support a hardware-limited conclusion.
- The remaining ceiling is mostly algorithmic and backend-related, especially embeddings and vector retrieval.

Outstandig actions:

1. Replace brute-force embedding retrieval with a vector-native index.
    - Target: `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py::embedding_candidates`
    - Rationale: large `ctx` runs spend substantial time in `embedding_candidates` and `_dot_similarity`.
    - Approach: move from Python-side full vector scanning to a vector index or ANN backend.
    - Heavy refactor: yes.
    - Expected gain: roughly `15%` to `35%` on large-repo `ctx`.

2. Introduce a long-lived embedding runtime or switch inference backend.
    - Target: `src/codira/semantic/embeddings.py::embed_texts`
    - Rationale: full indexing remains dominated by embedding inference; small `ctx` still pays cold-start cost.
    - Approach: keep the model warm in a daemon/worker process, or move to a faster runtime such as ONNX/OpenVINO/CTranslate2-class tooling if compatible.
    - Heavy refactor: yes.
    - Expected gain: roughly `15%` to `30%` on large full indexes, plus `1s` to `3s` on small cold `ctx`.

3. Persist or precompute reference-scan data for `ctx`.
    - Target: `src/codira/query/context.py::_collect_reference_rows`
    - Rationale: the recent cache work already paid off, proving the path is performance-sensitive.
    - Approach: avoid rescanning repository files per query; persist searchable reference data during indexing.
    - Heavy refactor: medium.
    - Expected gain: roughly `10%` to `25%` on JSON-heavy and large text-heavy `ctx`.

4. Continue optimizing the JSON analyzer acceptance path, but treat it as a lower-priority, JSON-specific follow-up.
    - Target: `packages/codira-analyzer-json/src/codira_analyzer_json/__init__.py`
    - Rationale: JSON is the current first-party outlier because `supports_path()` is content-sensitive, while Python, C, and Bash accept deterministically by extension.
    - Concrete remaining optimization: accepted JSON files are still fully loaded in `supports_path()` and then fully loaded again in `analyze_file()`.
    - Approach: avoid the second full JSON load by reusing classification and parsed payload for accepted files, if that can be done without breaking analyzer contracts or indexer boundaries.
    - Heavy refactor: low to medium.
    - Expected gain: likely smaller than the latest JSON win and currently unquantified; worth treating as a measured follow-up, not a guaranteed major gain.
    - Benchmark gate decision after implementation planning: do not proceed with this change in the current patch set.
    - Benchmark gate result: on the `cldr-json` corpus, `supports_path()` took about `7.989s`, but only `50` files were accepted and `analyze_file()` across those accepted files took about `0.005s` total.
    - Conclusion: the accepted-file double load is not the meaningful hotspot on the measured corpus, so the JSON analyzer was intentionally left unchanged.

5. Do not prioritize the tiny regressions.
    - Target: `help`, `plugins`, `caps`, warm-index micro-deltas
    - Rationale: the observed regressions are too small to matter before items 1 to 4.
    - Expected gain: negligible.

## Roadmap Snapshot Cross-Reference

Source note:

- The following mapping is based only on local snapshot files `issues.json` and `milestones.json`.
- Both files exist, parse successfully, match the expected schema, and are not paginated (`hasNextPage: false` at top level and inside milestone issue lists).

### Objective 3 items already related to open issues

1. Replace brute-force embedding retrieval with a vector-native index.
    - Related open issue: `#20 Feature: Introduce Optional Vector Database Backend for Semantic Retrieval`
    - Milestone: `#7 Phase 5`
    - Match quality: strong
    - Reason: issue `#20` explicitly targets vector-database-backed semantic retrieval and names performance-sensitive semantic retrieval as the motivation.

2. Introduce a long-lived embedding runtime or switch inference backend.
    - Related open issue: `#22 Feature: Daemon Mode for Incremental File Watching and Automatic Reindexing`
    - Milestone: `#7 Phase 5`
    - Match quality: partial
    - Reason: `#22` covers daemon mode and long-lived process infrastructure, which is directly relevant to keeping embedding runtime warm.
    - Related open issue: `#28 feat(embeddings): Add embeddings calibration script (hardware-aware auto-tuning)`
    - Milestone: `#2 Phase 1`
    - Match quality: partial
    - Reason: `#28` covers hardware-aware tuning of embeddings, but not a new inference runtime or model-serving architecture.
    - No open issue directly covers switching the inference backend to ONNX/OpenVINO/CTranslate2-class tooling.

3. Persist or precompute reference-scan data for `ctx`.
    - Related open issue: none found
    - Match quality: none
    - Reason: no visible open issue in the local snapshots targets `ctx` reference expansion, stored reference-scan data, or eliminating repository rescans during `ctx`.

4. Continue optimizing the JSON analyzer acceptance path.
    - Related open issue: none found
    - Match quality: none
    - Reason: no visible open issue targets the remaining JSON-specific acceptance-path cost, including double loading of accepted JSON files.

5. Do not prioritize the tiny regressions.
    - Related open issue: none needed
    - Match quality: not applicable

### Completely new points relative to the current local roadmap

- Objective 3 item `3`: persist or precompute reference-scan data for `ctx`
- Objective 3 item `4`: continue optimizing the JSON analyzer acceptance path as an explicit performance follow-up
- Objective 3 item `2`, specifically the inference-backend replacement path

### Partially covered points

- Objective 3 item `2` is only partially covered:
  - `#22` covers daemon/process lifetime infrastructure
  - `#28` covers embeddings calibration and hardware-aware tuning
  - neither issue explicitly covers changing the embedding inference runtime itself

### Existing issues relevant to Objective 3, ordered by closeness

1. `#20 Feature: Introduce Optional Vector Database Backend for Semantic Retrieval`
    - milestone `#7 Phase 5`
    - strongest match for Objective 3 item `1`

2. `#22 Feature: Daemon Mode for Incremental File Watching and Automatic Reindexing`
    - milestone `#7 Phase 5`
    - partial match for Objective 3 item `2`

3. `#28 feat(embeddings): Add embeddings calibration script (hardware-aware auto-tuning)`
    - milestone `#2 Phase 1`
    - partial match for Objective 3 item `2`

4. `#10 Enable immediate support for multiple production-grade backends`
    - milestone `#2 Phase 1`
    - indirect architectural relevance only
    - this is backend architecture, not a direct performance fix for the current hotspots
