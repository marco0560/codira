# codira-clang-frontend

This optional package provides one Clang LibTooling frontend for Codira's C
and C++ analyzer plugins. It is independent of the Codira core package and has
no Python runtime dependencies. Without an explicitly configured helper and
profile, analyzers continue using their existing frontend.

## Native helper lifecycle

The packaged C++ source is `src/codira_clang_frontend/native/clang_frontend.cpp`.
Build it only as an explicit developer or operator step, using the matching
Clang/LLVM development headers, libraries, compiler, and resource directory.
The build API requires the compiler and library paths/names as inputs. It does
not search `PATH`, invoke a build system, infer linker flags, or run during
package import or indexing. A build receipt records the compiler invocation,
binary and source hashes, resource probe, exact argv, and immutable raw build
stdout/stderr. A failed build leaves its attempt outputs in place.

For example, after installing the optional package and identifying the local
LLVM installation, the operator can run:

```bash
python -m codira_clang_frontend.build_helper \
  --compiler <absolute-clang-cxx-driver> \
  --llvm-include-dir <absolute-llvm-include-directory> \
  --llvm-library-dir <absolute-llvm-library-directory> \
  --clang-cpp-library=<exact-clang-cpp-link-argument> \
  --llvm-library=<exact-llvm-link-argument> \
  --output <new-helper-path> \
  --receipt <new-build-receipt-path>
```

The helper is never compiled automatically by `analyze`. The dynamically
loaded LLVM/Clang shared-library closure is currently recorded as
`runtime_shared_library_identity: not_hashed`; deployments must keep the
matching runtime libraries available.

## Compile profiles

Choose exactly one explicit source of compiler argv:

* `from_compile_commands` reads one unique matching `compile_commands.json`
  row without executing it.
* `from_captured_profile_json` loads one generic
  `codira.clang-frontend-profile/2` record selected by exact source path and
  source SHA-256. It is not coupled to a pilot or cohort identifier.
* `from_captured_argv` binds an exact captured argv and its retained evidence.

The profile retains the complete original argv and working directory. The
frontend's result separately records the exact audited source-analysis argv
and transformations, such as removal of output-only `-Xclang -ast-dump=json`
and addition of `-fsyntax-only`. Compiler options are otherwise forwarded to
Clang so it can diagnose unsupported options. Execution-control/plugin flags
are held explicitly.

A profile is cache-complete only when it binds the source, all compiler-observed
dependencies, Clang's ordered effective include search roots, recursive search
directory membership, and a controlled or explicitly captured compiler
environment. Use `ClangFrontend.prepare_profile` before indexing to run the
exact retained profile through the selected helper and persist a new immutable
complete profile. Preparation does not build the helper. If historical
ambient include settings were not captured, preparation records the controlled
no-ambient environment used for that new profile; it does not claim to
reproduce the historical environment.

Preparation also binds the target triple from Clang's initialized `TargetInfo`
and the exact sysroot setting from its `HeaderSearchOptions`. The result exposes
these as `CompilationContext`; analysis compares its fresh native context with
the prepared profile and holds indexing on a mismatch or an unbound profile.
Schema `/1` captured profiles remain readable as partial inputs to explicit
preparation; they cannot qualify for complete indexing until target/sysroot are
bound. Sysroot paths are context metadata, not recursively hashed as a tree:
freshness covers the files Clang actually observed and the effective search-root
membership already captured for that invocation. This does not claim coverage
of unused sysroot files.

Dependency contents and include-root membership are checked for index-cache
freshness. Membership traversal follows symlinked child directories with
inode-based cycle detection, allowing newly added candidate headers beneath
standard system symlink roots to invalidate cached analysis. This can cost
more than hashing only previously included files, especially for broad system
roots. The source file's parent and any parsed dependency parent not already
covered by a recursive search root are also captured because quoted includes
search relative to the including file. Keep the attempt output directory outside
all captured include roots and source/dependency parents; `analyze` rejects an
overlap before writing its reservation or streams. Permission and I/O failures
make preparation incomplete rather than silently skipping entries.
`captured_profile_fingerprint` provides a
no-Clang fallback identity when strict profile reload detects stale evidence;
it hashes current declared files, search-root membership, and receipt-named
toolchain files so edits invalidate prior results.

## Result and fallback semantics

Native protocol v3 records typed includes, preprocessing events, documentation,
source declarations, callable metadata, and calls
owned by their callable USR, along with source spans, diagnostics, provenance,
dependency evidence, helper stdout/stderr digests, and explicit status and
coverage reasons. Calls are assigned to a definition when both a prototype
and definition share one USR. Calls without a reported owner remain visible as
unowned calls. Unknown provenance stays `unknown`; the frontend does not
promote it to source-written.

Native protocol v6 adds a `macro_definition_link` to every macro-expansion
event. A resolved link names the active physical definition selected by Clang
and includes the exact source spelling of its name token, spelling/expansion
coordinates, and function-like status. When Clang cannot provide a physical
definition record, the event carries an explicit bounded unavailable reason.
The link comes from the active `MacroDefinition` passed to the preprocessor
callback, so same-name redefinitions retain their selected definition site.
It does not infer a definition from a macro name alone.

Protocols v3 through v5 remain readable for existing frontend behavior. Their
macro-expansion events decode with `macro_definition_link_status` set to
`legacy_protocol` and no link; a v5 response cannot claim the v6-only field.
Consumers that require the definition edge must hold legacy events and v6
unavailable links. They must also verify the returned path and byte offset
against the exact source/profile dependency hashes before using the link as
source evidence.

Malformed protocol data, helper failure, nonzero Clang tool return codes, and
fatal/error diagnostics cannot produce a complete successful result. Optional
frontend unavailability or a held/failed result is for the analyzer plugin to
map to its explicit fallback status. The shared package does not silently
claim a Tree-sitter fallback as a successful Clang parse.

## Requested header projection

`ClangFrontend.analyze_header` accepts a `HeaderProjectionRequest` resolved
from complete captured dependency manifests. The request keeps the physical
header path and digest separate from the owning translation unit and its exact
captured argv. A unique captured owner is selected automatically; multiple
owners are held unless the caller selects one of the candidate profile
identities explicitly. The native helper parses the owning translation unit,
then filters reported physical entities to the requested header. Internal
linkage identity remains scoped to the actual translation unit. Header requests
require native protocol v4; ordinary translation-unit requests continue to
accept the existing v3 protocol.

Generated headers must exist before preparation begins. The preparation CLI
never runs a project build and never guesses compile flags. Its request JSON
names every TU profile source, generated header, helper, and build receipt:

```bash
python -m codira_clang_frontend.header_projection_cli \
  --request <absolute-request-json> \
  --output-dir <new-immutable-run-directory>
```

The CLI prepares incomplete captured TU profiles before owner discovery,
retains raw helper streams and per-TU/per-header checkpoints, and writes one
preparation summary with missing or ambiguous contexts explicit. Preparation
completion is profile/context evidence, not semantic parity qualification. Resume only the same
output directory with the unchanged request, helper, and receipt:

```bash
python -m codira_clang_frontend.header_projection_cli \
  --request <same-absolute-request-json> \
  --output-dir <same-run-directory> \
  --resume
```

If any bound input changes, start a new output identity; old checkpoints are
never silently reused.

An analyzer can resolve and parse a requested header directly:

```python
resolution = resolve_header_projection(header_path, captured_profiles)
if resolution.request is not None:
    result = frontend.analyze_header(
        resolution.request,
        attempt_dir=attempt_directory,
        attempt_id=attempt_id,
    )
else:
    hold_status = resolution.status
    owner_candidates = resolution.candidates
```

`FrontendResult.requested_source_path` and `requested_source_sha256` identify
the physical requested header. `translation_unit_path` and
`header_projection_identity` identify the captured owner context and bind the
projection. The selected language is `resolution.request.owner_profile.language`;
callers should use an explicit owner identity when multiple language or TU
contexts are candidates.

Each `analyze` call requires a durable attempt directory. It atomically
reserves its attempt identity before starting the helper and persists exact
stdout and stderr bytes before decoding. Reused attempt identities fail before
another process can run. The package does not decide where an application
stores those durable attempts; plugins should configure a stable per-attempt
artifact directory.

## Public API

The package exports `ClangFrontend`, the typed `CompileProfile` and result
records, profile loaders, `create_frontend_profile`,
`frontend_profile_fingerprint`, and `captured_profile_fingerprint`. The latter
two fingerprint functions do not invoke Clang. The package itself does not
depend on Codira core DTOs or analyzer plugins.

Compiler identities use `clang.usr.v1`; internal-linkage identities additionally
bind the actual translation unit and declaration file. Source-invoked generated
callables still require compiler-origin persistence in the adapters and remain
explicit partial coverage until that representation is implemented. See
[ADR-038](../../docs/adr/ADR-038-clang-metadata-and-exact-call-identities.md).
