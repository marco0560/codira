# Clang reference and installed-distribution qualification — 2026-10-28

The independent reference lane and the local installed-distribution check serve
different purposes. Neither adds verified original files to the remediation
ledger. That ledger remains 5,030 verified, 716 separated, and 20,016 open.

## Independent reference capture

`scripts/clang_reference_facts.py` runs a receipt-bound Clang CLI AST dump without
consuming the LibTooling helper's entity output. This tests Clang parity through
an independent extraction path; both paths still use the same compiler.

The immutable scope manifest selects source-hash-joined rows from the pilot
manifest. Counts come from that scope. The current prepared cohort has 50 LLVM
originals, 25 C and 25 C++; the broader pilot has 200 originals. These denominators
must not be interchanged.

The capture preserves the original driver's argv0 while executing the explicitly
bound Clang binary. It streams raw stdout and stderr to exclusively created
files, records terminal status before parsing, and retains failed attempts.
Extractor identity and compiler, source, profile, resource and dependency checks
bound the reference inputs. Changed inputs prevent qualification credit.

Location normalization is tied to the inspected `llvmorg-22.1.8`
`clang/lib/AST/JSONNodeDumper.cpp` implementation. Repeated filenames follow its
global serialized location state; `includedFrom` does not change that state.
Macro spelling precedes expansion. Offsets and lines are physical; columns are
presumed and must not reject otherwise valid physical offsets.

Overlapping AST calls are grouped by physical range, preserving all semantic
caller contexts and marking multiple contexts or AST candidates ungraded. Function
pointers and returned-pointer invocations must not acquire guessed direct
targets. Unsupported macro, template, implicit, header and harness evidence
remains explicitly ungraded. Native acceptance and selected matching facts do
not establish whole-file semantic parity.

From the repository root, with the project environment installed, supply the
existing pilot, scope, prepared-profile and tool receipts as absolute paths:

```bash
uv run python scripts/clang_reference_facts.py \
  --cohort-manifest <PILOT_MANIFEST_JSON> \
  --scope-manifest <SOURCE_JOINED_SCOPE_JSON> \
  --profile-manifest-root <PREPARED_PROFILE_ROOT> \
  --preflight <PROFILE_API_PREFLIGHT_JSON> \
  --build-receipt <CLANG_BUILD_RECEIPT_JSON> \
  --output-root <NEW_DURABLE_RUN_DIRECTORY> \
  --selection-id <SELECTION_ID>
```

Repeat `--selection-id` for additional selected rows. Expected outputs include
raw streams, terminal and normalization records, input validation and a scope
coverage receipt. A zero process exit means recorded execution completed, not
that semantic qualification passed. Inspect those records. Following a failed
attempt, preserve its directory and use a new immutable output identity.
Existing raw ASTs can also be normalized later with a separately hash-bound
extractor; retain the original capture's evidence limitations.

Profile preparation records distinguish input and prepared profile status.
Its frontend status and coverage describe analysis before dependency capture;
the returned prepared profile describes the newly bound indexing inputs.
Neither status is an independent semantic grade.

## Current installed-distribution evidence

At source commit `422196a03035a512fc9380d3ef603076f064f1ef`, a fresh Linux x86_64
Python 3.13.13 environment exercised these built distributions:

| Distribution | Version |
| --- | --- |
| `codira-clang-frontend` | 0.4.0 |
| `codira-analyzer-c` | 2.0.19 |
| `codira-analyzer-cpp` | 2.0.48 |
| `codira` | 2.4.7.post1.dev118 |

The frontend wheel and sdist contain matching native C++ source. Clean installed
module origins and C/C++ analyzer entry points were checked. Dependencies were
installed from a frozen, hash-pinned lock export after a retained offline-cache
failure. The installed frontend built the helper with Clang 22.1.8, prepared a
fresh helper-bound profile, and parsed the authored alias fixture. The installed
C++ analyzer accepted its configuration and produced indexable artifacts; its
coverage remained partial for `generated_declaration`. This did not exercise
persisted indexing or querying on either backend.

The native source SHA-256 is
`c68b14f9aaa879dd0384e6b3f6d9ff012b3fcfa66c65f48603b69db0c993db50`;
the installed-source helper SHA-256 is
`af62dc2f29c13074a5ee068ed1808ee8e0a235dcb209d7aab2f27129de2b6234`.
Supplemental loader evidence hashes the resolved Clang/LLVM libraries, with no
unresolved dependencies. Durable wheel and sdist members preserve source
provenance independently of the disposable installation directory.

Evidence is retained under the analysis family
`.artifacts/analysis/parser-diagnostics-20261017-r1/`:

- `clang-json-location-provenance-20261028-r2/source-evidence.json`:
  version-specific location implementation and retained source excerpt.
- `clang-reference-facts-comparison-20261028-r4-denominator-correction/`:
  source-joined scope clarification; earlier exploratory attempts remain intact.
- `clang-reference-facts-renormalization-20261028-r2/normalization-receipt.json`:
  hash-bound extraction from two retained ASTs, including ambiguous physical
  sites and the original capture-window stability limitation.
- `clang-installed-distribution-qualification-20261028-r1/qualification-result-r1.json`
  and `evidence-manifest-r1.json`: installed distribution results and raw evidence.
- Its `provenance-extension-r1/`: archive linkage, reproduction instructions,
  loader evidence and append-only manifest extension.

This host check establishes no macOS or Windows qualification, supported-platform
policy, compiler-independent semantic truth, corpus admission or default switch.
Tree-sitter remains the default. Whole-file qualification requires independent
required-fact coverage and persisted checks on both backends; the full Clang
port and original remediation objective remain open.
