# Clang integration qualification fixtures

This versioned fixture adds a source-written C++ type alias. The earlier `clang_frontend_integration` fixture remains frozen for its completed r6c proof.

These two small translation units are the independent source-written oracle
for C and C++ qualification. `oracle.json` is authored from fixture source,
not from Clang output or analyzer output. The C case covers a macro-expanded
call, a prototype before its later definition, and compile-time inactive code.
The C++ case covers namespace and class ownership, overloads, a method call,
and a template call whose compiler instantiation must remain distinguishable
from the written template.

`postgres_thread_descriptor_oracle.json` binds selected declarations and calls
to the original non-LLVM PostgreSQL C source. It asserts the active pthread
branch, both source-spelled `sqlprint` calls, callable ownership, and excludes
Windows-only calls. Its oracle deliberately avoids the source's `#line`
remaps and macro-mediated call locations.

`write_fixture_compilation_database.py` writes an exact local compile database
for the two controlled fixtures using the retained Clang 22 executable. The
commands do not guess target or include flags. Native preparation observes the
dependency closure and search-root memberships before producing reusable
profiles. The oracle records header-only and compile-profile changes that must
change the selected callable set while source bytes stay unchanged.

The initial exact compile database is
`.artifacts/analysis/clang-integration-qualification-20261026-r1/fixture-inputs-r2/compile_commands.json`;
the earlier `fixture-inputs-r1/` receipt is preserved because the C source
changed to add the prototype-before-definition case. The source-bound prepared
fixture profiles are at
`.artifacts/analysis/clang-integration-qualification-20261026-r1/fixture-profile-preparation/fixture-source-profiles-r1/prepared-profiles.json`.
The separate copies under `fixture-targets/fixture-profiles-r1/` are an older
preparation identity; actual Codira indexing must use the source-bound
manifest.

PostgreSQL captured-profile exports remain immutable under `profiles-r2/`
through `profiles-r5/`. CFP-113's original retained profile was freshly
prepared into
`prepared-profiles-r5/850c1e19b81cf38f423af9d4db0e667c66ccf27911ae7bbfa3e338815cc7fb10.json`.
The prepared profile binds the original source, 102 observed dependencies,
and eight effective or quoted search roots. CFP-115 remains partial because
its dependency closure was not hash-proven; it is a fallback negative case,
not a Clang pass. There is no retained non-LLVM C++ original profile in the
current cohort.

Direct native evidence is graded separately from Codira persistence. The C
source-bound result matches its oracle. A fresh C++ helper r5 result and an
offline decode of the exact saved native response match source symbols, method
call ownership, overload target types through native target USRs, and the
written template versus compiler-instantiation distinction. Receipts are
under `offline-oracle-grading-r5/` and bind helper, profile, source, and decoder
digests.

The current Codira `CallSite` stores caller ownership, target name, and source
position but not overload signatures or target USRs. Index-level checks must
not claim exact overload dispatch; an overloaded target that cannot be
resolved by the persisted DTO must remain unresolved rather than bind to a
same-name overload.

Qualification acceptance requires actual Codira indexing on SQLite and
DuckDB under a frozen assembled runtime. Persisted checks must independently
assert compiler-selected source symbols, owned calls, source positions,
profile identity, `clang-*` grammar, reliable fact categories, and explicit
omissions. Partial DTO coverage remains visible; a parsed Clang attempt or
successful index command does not itself qualify a plugin. Earlier
exploratory index attempts are retained under `index-runs/`; they either
discovered no files or selected Tree-sitter fallback with
`clang_entities_outside_supported_*_dto_scope`. Those attempts are not Clang
successes. A partial-profile fallback must persist its diagnostic and selected
frontend mode.
