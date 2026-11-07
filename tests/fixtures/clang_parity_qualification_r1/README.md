# Clang parity qualification fixtures

`source-oracle.json` describes declarations, calls, ownership and source lines
from the authored fixture files. It is not generated from Clang output or an
analyzer result. All C++ identities remain fully qualified. The paired
`same-name-a/foo.c` and `same-name-b/foo.c` files deliberately use the same
basename and internal symbol spelling; their exact identities must still
resolve only within their canonical translation unit.

The fixtures cover local and system includes, macros and macro-expanded calls,
C records/enums/typedefs/fields/globals, C++ namespaces/aliases/nested types,
enum members, fields, overloads, callable ownership, pointer-indirect calls,
Doxygen comments, prototype versus definition, and a cross-translation-unit
callee. `shared_internal.hpp` defines an internal-linkage function used by
two translation units; its identities must differ by owning TU, and neither
call may bind across TUs while its header context is ambiguous.
`out_of_line/Owner.hpp` declares a class while `Owner.cpp` defines its
method; a Clang analysis of the implementation must not invent a class row in
the implementation file. The existing `tests/fixtures/clang_frontend_integration`
fixture remains included for its source-selected conditional, macro provenance,
template-instantiation, and original PostgreSQL claims.

## Qualification runner

Use one generic runner for profile preparation, source-oracle validation,
freeze audits, and both backend snapshots. Start with a fresh output directory
for each attempt; profile preparation refuses to reuse an existing one.

To prepare selected translation units from a captured compilation database:

```bash
PARITY_WT=/absolute/path/to/clang-parity-oracles-r1
FRONTEND_SRC=/absolute/path/to/metadata-worktree/packages/codira-clang-frontend/src
PYTHONPATH="$PARITY_WT/src:$FRONTEND_SRC" /absolute/path/to/root/.venv/bin/python \
  "$PARITY_WT/scripts/clang_parity_qualification.py" \
  --oracle "$PARITY_WT/tests/fixtures/clang_parity_qualification_r1/source-oracle.json" \
  --fixture-root "$PARITY_WT/tests/fixtures/clang_parity_qualification_r1" \
  --prepare-profile-source "$PARITY_WT/tests/fixtures/clang_parity_qualification_r1/parity_cpp.cpp" \
  --profile-root "$PARITY_WT" \
  --compile-database /absolute/path/to/captured/compile_commands.json \
  --helper /absolute/path/to/frozen/clang_frontend \
  --build-receipt /absolute/path/to/frozen/build-receipt.json \
  --profile-output "$PARITY_WT/.artifacts/analysis/clang-parity-qualification-<run-id>/profiles" \
  --attempt-prefix clang-parity-<run-id>
```

Pass every requested translation unit with another `--prepare-profile-source`.
The command uses the captured compiler arguments as written, verifies the helper
against its receipt, and retains raw helper stdout/stderr plus attempt status.
A complete profile means its source digest and dependency closure are captured;
it does not establish semantic parity.

For a freeze, pass named `--freeze-file ROLE=PATH` entries for every authored
source, analyzer module, prepared profile, helper binary, and build receipt.
Pass public runtime constants as `--public-constant ROLE=MODULE:ATTRIBUTE`,
including `PROFILE_SCHEMA`, `LOGICAL_SCHEMA_VERSION`, and each backend's public
`SCHEMA_VERSION`. `--write-freeze` creates a new immutable receipt; use
`--audit-freeze` to compare later inputs and retain any differences.

For semantic grading, pass exactly one `--snapshot` from SQLite and one from
DuckDB. A snapshot has `snapshot_version: 1`, a backend name, per-source arrays
for the oracle fact categories, `header_context` owner/profile rows, and an
`identity_observations` map keyed by the oracle's identity references. Call
rows must include caller/callee stable IDs, exact target identity, resolution,
source coordinates, and the target definition's physical source/line. The
grader preserves qualified names, distinguishes overload definitions, rejects
unexpected duplicate callable/call/field/type rows, and keeps external,
indirect, missing, and ambiguous exact targets unresolved. A display-name match
alone never passes.

The C and C++ macro-generated callable expectations are marked `pending` in the
oracle because the current generic `GeneratedCallableProvenance` format cannot
faithfully encode Clang's compiler-origin token evidence. The runner reports
each expected callable separately, including its invocation line and byte
span. A backend phase can pass its ordinary required rows while `scope_complete`
remains false until both generated provenance rows are represented accurately.
