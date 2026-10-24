# Clang frontend pilot envelope v1

The Python API is `codira`-independent and stdlib-only:

```python
from scripts.clang_frontend_pilot.adapter import adapt_selection
```

`adapt_selection(row, manifest_source, compile_database, repository_root,
helper_path, *, stderr_path=None, stdout_path=None, force_hold_reason=None)`
returns one raw JSON-compatible envelope. `compile_database` is a decoded list
of compilation-database objects. The
CLI `run.py` provides manifest loading, deterministic selection order, NDJSON
output, and checkpointing. Each selected manifest row produces one terminal
envelope, including held rows. The envelope binds the manifest and row identity
without embedding source contents.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `capture_mode` | `source_relevant` by default, or explicit `full` for legacy header-wide record capture. It is bound into request, envelope, and checkpoint identity. |
| `schema_version` | `codira.clang-frontend-pilot-tu/1`. |
| `pilot_id` | Immutable pilot identity, `clang-frontend-pilot-20261024-r1`. |
| `manifest_source` | Cohort manifest path, SHA-256, schema version, and cohort metadata. |
| `selection_row` | Full copied manifest row, including source-intent and profile evidence. |
| `selection_id` | Exact cohort row ID. |
| `population_class`, `language` | Exact manifest values (`llvm`/`nonllvm`, `c`/`cpp`). |
| `repository_id`, `repository_revision` | Exact repository identity and pinned revision. |
| `repository_relative_path`, `source_path`, `source_sha256` | Relative/absolute source binding and expected digest. The source path is resolved beneath the supplied checkout root and checked both before and after Clang. |
| `classification_disposition`, `feature_family`, `family_evidence` | Exact source-intent cohort labels and evidence. |
| `profile_context_status`, `profile_evidence`, `context_limitations` | Exact profile-context facts from the cohort manifest. |
| `context_status` | Repeats the input `profile_context_status`; the value is never rewritten after execution. |
| `observed_context_status` | `complete`, `incomplete`, `unavailable`, or `invalidated`, based on actual dependency closure and source recheck. |
| `native_execution` | Whether the fixed LibTooling helper ran, separate from parser outcome. |
| `frontend.status` | `parsed`, `diagnostics`, or `not_run`. |
| `independent_qualification` | Starts at `not_run`; Clang output never qualifies itself. |
| `status`, `hold_reasons` | `complete`, `partial`, or `held` describes only adapter/frontend evidence capture. It never means source correctness or a fix. Errors and missing context remain in the denominator. |
| `original_compile_command` | Original cwd, original command text or argv, database binding, and a PATH/filesystem-resolved compiler candidate path/hash. The original compiler is never executed; this resolution is not proof of the executable used when the database was captured. |
| `clang_adaptation` | Clang compiler path/version/hash, compiler-probed resource directory and `stddef.h` hash, LibTooling helper path/hash, logical frontend argv, fixed helper invocation, ordered transformation ledger, unsupported context, helper exit and stderr digest. The loaded LLVM/Clang shared-library binaries are not individually hashed (`runtime_shared_library_identity=not_hashed`). |
| `dependency_closure` | Files reported by preprocessing with path/hash, closure status, and digest over the sorted JSON file list. |
| `frontend` | Compact declarations, calls, preprocessing/include events, and diagnostics. No full AST dump is emitted. |
| `unmodeled_fields` | Explicit limits of this pilot projection. |

The pilot reports function declarations, call expressions, and preprocessor
facts. It does not model all Codira DTO fields or parity; in particular,
caller/enclosing-callable ownership links are not exported. Declaration counts
and hashed dependency paths do not establish complete file or header coverage.

`source_relevant` does not change the Clang parse, diagnostics, include graph,
or dependency hashing. It exports declarations whose expansion originates in
the main translation unit, retains main-file preprocessing events and header
macro definitions referenced by main-file expansions, and aggregates counts
for omitted header declaration/preprocessor records. Omitted projection records
are not evidence of missing parser coverage. Explicit `full` mode retains the
legacy header declaration and preprocessing records for replay and comparison;
its output can be substantially larger.

## Location and record fields

Every location view has `{path, line, column, offset}`. `offset` is a Clang
source byte offset; unavailable fields are `null`. A `location` has separate
`spelling` and `expansion` views plus `is_macro`. Ranges have `begin` and `end`
views with the same spelling/expansion shape.

Declarations retain separate physical and generated identities:

```json
{
  "identity": {
    "usr": "c:...",
    "kind": "written|implicit|template_instantiation",
    "instantiated_from": "c:..."
  },
  "decl_kind": "function|method|constructor|destructor|conversion",
  "name": "run",
  "qualified_name": "demo::run",
  "signature": "int demo::run(int value)",
  "signature_kind": "derived_display_only",
  "function_type": "int (int)",
  "has_prototype": true,
  "is_variadic": false,
  "method_qualifiers": {"is_method": false},
  "parameters": [{"name": "value", "type": "int"}],
  "location": {"spelling": {}, "expansion": {}, "is_macro": false},
  "range": {"begin": {}, "end": {}}
}
```

Declarations are not deduplicated by name, signature, or source location. The
identity kind distinguishes source-written declarations from implicit,
template-instantiated, and explicit template-instantiation declarations.
Explicit specializations remain `written`. `signature` is a convenience
display assembled from names and parameters; it can omit source-language type
distinctions. `function_type` is Clang's printed declaration type and
`has_prototype` preserves the C prototype versus old-style declaration split.
`method_qualifiers` records C++ method cv/ref, static, virtual and constructor
kind facts. These compiler-produced fields are authoritative in the pilot.

The AST is Clang's active semantic AST: declaration and call facts from
inactive conditional branches are unavailable. Preprocessor events retain
conditional directives and their active state. Implicit declarations and
template instantiations may appear as additional records and are explicitly
flagged; they do not establish physical source-written identities.

Calls have a `site_identity` from spelling path and byte offset, an independent
`expansion_identity`, `origin` (`source_written` or `macro_replacement`),
resolved callee identity/name/signature when available, argument text and
source spans, and the same spelling/expansion location views. Macro-generated
helper calls therefore remain distinct from their source invocation.
Resolved callees expose the same `function_type` and `has_prototype` fields;
their `signature` is also marked as display-only.
The AST's resolved semantic facts may describe macro replacement expansions;
the physical written call remains separately identified by spelling location.

Preprocessor callbacks retain macro definitions/undefinitions/expansions,
conditional directives and include attempts. Resolved include paths are listed
separately and feed dependency hashing. A missing/ambiguous compile row,
no-profile context, unsupported flag, source mismatch, helper error, or
incomplete dependency closure has an explicit hold reason and keeps the cohort
selection row in output. A command-backed partial profile may be run; its input
status remains `partial_profile`, while observed dependency closure records
what the frontend actually read and hashed. This is not semantic qualification.

## CLI and helper build

One-row or batch invocation:

```bash
uv run python -m scripts.clang_frontend_pilot.run \
  --manifest <cohort-manifest-r1.json> \
  --compile-commands <compile_commands.json> \
  --repository-root <checkout> \
  --helper <built-libtooling-helper> \
  --output <durable-results.ndjson> \
  --checkpoint <durable-checkpoint.json> \
  --selection-id <selection-id>
```

The runner defaults to `--capture-mode source_relevant`. Set
`--capture-mode full` for the legacy output projection. The mode is part of
checkpoint identity, so changing it requires a fresh output/checkpoint path.

Omit `--selection-id` to process all manifest rows mapped to the supplied
checkout and compile database. The runner verifies the checkout's pinned Git
revision. A missing compile database is an explicit held outcome for every
selected row. An explicit `--helper` is required. The runner never
evaluates `compile_commands.command`, invokes a build system, or executes the
original compiler. `command` is parsed with POSIX `shlex.split`; `arguments`
is preserved directly. Ordinary driver arguments are forwarded unchanged so
Clang can diagnose unsupported compiler options. Output, dependency, linker,
and assembler actions are stripped with explicit ledger entries;
plugin-loading, direct `-cc1`, response-file, wrapper, and implicit driver
configuration arguments are held before the helper runs. Existing
output/checkpoint identities are resumed or rejected. Immutable row records and raw stdout/stderr
are never overwritten. Resume verifies source and dependency hashes, original
compiler binary, Clang compiler/helper and build receipt, manifest/database
digests, and adapter producer identity.

The qualified build environment has Clang/LLVM 22.1.8, headers at
`/usr/lib/llvm/22/include`, and monolithic libraries at
`/usr/lib/llvm/22/lib64`. The helper build receipt captures the selected
compiler's fixed `-print-resource-dir` argv, stdout, exit status, resolved
directory, and SHA-256 of its builtin `include/stddef.h`. The adapter validates
that proof and adds the resulting `-resource-dir` explicitly unless the
original profile selected a different directory, in which case the row is
held. The build helper passes this argv directly to
`subprocess.run(..., shell=False)` (the output path is caller supplied):

```text
clang++-22 -std=c++20 -O2 -I/usr/lib/llvm/22/include \
  <helper-source.cpp> -L/usr/lib/llvm/22/lib64 \
  -Wl,-rpath,/usr/lib/llvm/22/lib64 -lclang-cpp -lLLVM-22 \
  -o <helper-output>
```

This is a comparison frontend prototype. Its output is raw Clang evidence, not
an independent correctness oracle, Codira DTO, indexing result, or claim that a
source file is fixed.
