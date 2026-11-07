# Clang frontend pilot cohort and context census

- **Pilot identity:** `clang-frontend-pilot-20261024-r1`
- **Canonical manifest:** `.artifacts/analysis/parser-diagnostics-20261017-r1/clang-frontend-pilot-20261024-r1/census-r4/cohort-manifest-r4.json`
- **Context report:** `.artifacts/analysis/parser-diagnostics-20261017-r1/clang-frontend-pilot-20261024-r1/census-r4/context-census-r4.json`

## Source snapshot and selection

The cohort is drawn from `classification-v79.jsonl`, SHA-256
`db96d98154254c80820c81ddf2a2f2bd56d7c62104d2f220be40a47de34db101`. The
snapshot contains 25,762 rows, including 20,016 open C/C++ analyzer rows. The
generator rechecked each eligible source against the classification SHA-256;
all 20,016 sources were present and matched.

The fixed cohort contains 200 rows, with 50 in each of four strata: LLVM/C,
LLVM/C++, non-LLVM/C, and non-LLVM/C++. The per-file C/C++ route comes from the
classification row's `analyzer` field. It is not inferred from a repository
name: for example, the cohort contains C inputs from the CPython and
VictoriaMetrics repositories. `.h` files can still have an ambiguous language
mode when no source-owned or compile-profile evidence specifies one; those
mode clues are retained per row.

Within each stratum, the generator first preserves all five open files joined
by exact path and source SHA-256 to the existing LLVM source-intent/parser-error
census. For both LLVM languages, exactly 25 of 50 rows have a retained exact
compile command and 25 do not. This deliberately oversamples known LLVM
profiles; that ratio is a cohort design, not a source-population context rate.
The remaining selection is balanced across source-evidence family, dependency
context status, source size, and repository, using SHA-256 of the fixed seed,
repository, relative path, and source digest as the deterministic order. The
five joined files provide explicit negative/control material; their source
markers are not proof that the full file is malformed, nor do they qualify a
production analyzer result.

The family labels are broad sampling hints derived from recorded evidence and
source paths. They are not adjudicated root causes. The exact per-row evidence
and overlap references are retained in the manifest. The generator is
`scripts/clang_frontend_pilot/generate_cohort.py`; it refuses a changed
classification digest, source digest mismatch, undersized stratum, or overwrite
of a non-empty output identity.

## Candidate distribution

| Population | C | C++ | Source-evidence families |
| --- | ---: | ---: | --- |
| LLVM | 50 | 50 | preprocessor/context 10; declaration/call/template 10; grammar/version 10; harness/control 13; unclassified 57 |
| Non-LLVM | 50 | 50 | preprocessor/context 29; declaration/call/template 2; grammar/version 7; harness/control 24; unclassified 38 |

The cohort spans nine repositories: LLVM (100), PostgreSQL (24), Redis (22),
CPython C inputs (21), fmt (15), zlib (9), Catch2 (5), VictoriaMetrics C
inputs (3), and inih (1). The fixed sample is balanced by LLVM/non-LLVM and
parser route; the available non-LLVM C++ population is smaller and more
concentrated than the LLVM population.

## Compile context and held cases

The generator reused only exact retained compile commands, compiler-backed
context results, and dependency evidence. It ran no compiler or build system,
and synthesized no flags. It hash-joined v79 candidates against the existing
C-ISL CMake `compile_commands.json`, which has 1,464 exact open-source joins
(75 C analyzer-route and 1,389 C++ analyzer-route files). The source file hash
is verified, and each selected command is bound to the database SHA and entry
index. Its SHA-256 is
`76117e04a519e76c834b75177adbb666b6a6aa90a09ff722a82dcde028bb6785`. This
compile database does not provide a dependency-closure proof, so an
available command remains a partial profile until required headers and
generated files are confirmed. The non-LLVM native captures add two C commands;
one has a hash-bound dependency closure. Profile status by population is:

| Population | Reproducible profile | Partial profile | No profile |
| --- | ---: | ---: | ---: |
| LLVM | 0 | 50 | 50 |
| Non-LLVM | 1 | 1 | 98 |

The 50 LLVM commands preserve the exact compile database spellings `cc` and
`c++`; the two non-LLVM profiles preserve `clang-22`. The adapter resolves and
records the original compiler binary identity, then records the Clang
syntax-only argv separately. It must not assume `cc` or `c++` means GCC or
Clang, and it must not invent a GCC-to-Clang transformation for no-profile rows.
Every one of the 148 no-command rows stays in the 200-row denominator. The
profile-balanced LLVM cohort is intentionally not a global estimate of context
availability.

The source census is measurement scope, not a claim that 200 compiler runs can
be qualified today. Report context coverage, held reasons, semantic grading,
frontend completion, diagnostics, and per-file cost separately. The full
selection and profile records are in the canonical manifest and context report
above; the earlier immutable census generations are retained alongside r4.
