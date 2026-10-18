# Rust parser recovery and remaining extraction omissions

This phase continues the analyzer diagnostic investigation on the isolated worktree.
The frozen diagnostic cohort contains 46 Rust files: two from Anyhow (edition 2021),
29 from Bevy and 15 from Zed (edition 2024). All 46 original files parse with the
retained unexpanded Rust 1.98.1 compiler AST probe. They are implementation gaps,
not malformed/future-syntax exclusions.

## Parser correction

The Rust plugin now builds coordinate-preserving views for six bundled grammar
omissions: tilde punctuation inside opaque macro token trees; complete outer
attributes decorating delimited components; lifetime-first `dyn` bounds; negative
integer const arguments; trailing commas in closure parameters; and nested type-path
turbofish separators. Complete isolated attribute/header/type probes constrain the
recoveries. Literals, comments and token trees remain opaque where appropriate.
Conditional attributes are not evaluated and no macro expansion, Cargo invocation,
compiler execution or type resolution enters the analyzer.

The original source continues to own signatures, names, literals, documentation,
parameter bindings and call coordinates. Projection preserves every byte/newline
coordinate. Existing clean trees are returned untouched; any residual error discards
the complete projected view and retains the original partial result. A failed view
never grants indexing permission.

The initial generalized closure-header search also visited unrelated correct
closures in a large Zed file. A retained py-spy profile identifies that search as
the running frame. The exploratory grading process was interrupted deliberately;
its first 34 receipts and exact input-source snapshots remain retained. Recovery
now considers trailing-comma candidates only in original error ranges. A regression
check with 100 unaffected closure pairs prevents repeated header probes. The corrected
native-item grading completes all 46 original paths.

Local versions advance to Rust distribution **2.0.2**, logical analyzer **4**, and
bundle **2.0.26**. Root pins, lockfile and package assertions agree. Storage schemas
and other analyzer versions do not change. No release is published.

## Independent checks and admission

The broader replay covers every `.rs` file in the three frozen repositories:
**3,870 files**, zero exceptions, zero regressions and **all 3,823 previously clean
complete artifact payloads unchanged**. The 47 previously partial paths become clean.
That includes the original 46 diagnostics plus Zed's
`crates/agent/src/tools/evals/fixtures/disable_cursor_blinking/before.rs`, outside the
original diagnostic ledger. Its original source independently passes the same native
edition-2024 syntax check, but it is not added to the frozen cohort or recovery count.

The focused Rust/bundle checks pass 40 tests. Native control probes separately accept
all 17 positive syntax fixtures and reject all 12 final malformed controls. Earlier
negative-control attempts included constructs accepted by the unexpanded compiler
parser despite their unresolved/type-invalid semantics. Those attempts remain in
`rust-native-controls-r1/` and `r2/`; they were replaced with demonstrated syntax
errors for the final `r3/` controls. No compiler/type-checking claim is inferred from
unexpanded parse acceptance.

Native item grading checks callable, macro, struct, enum, trait, impl, constant and
module identities and their physical declaration lines. It compares all corresponding
native items, including nested ones; it does not silently drop missing targets to
admit a path. All 46 original files are parser-clean, but only **27 match all graded
items**, totaling **564 declarations**: Anyhow two, Bevy 20, Zed five. These 27 paths
qualify for classification-v13 after the full gate. That ledger has **627 verified
recoveries** and **24,692 unresolved paths**, of which 19 are Rust.

The comparison excludes type aliases, statics, use trees, calls, variables, fields
and expanded/resolved semantics. Impl identity comparison uses kind and physical
start line; named items additionally require the exact native name. Thus this is a
bounded declaration-identity qualification, not complete Rust semantic evaluation.

## Extraction defects still open

The remaining **19 files omit 565 native items**; there are no extra graded items
and no native-reader limitations in this comparison. Inspection of the extractor
confirms that it visits root items and methods below root traits/impls, but skips
items inside inline modules and local/associated declarations. Those files stay
unresolved even though their parser errors are corrected. Follow-up must recover
these scopes with durable identities and native verification rather than weakening
the oracle.

| Repository-relative path | Missing graded items |
| --- | ---: |
| Bevy: `crates/bevy_input_focus/src/lib.rs` | 12 |
| Bevy: `crates/bevy_light/src/lib.rs` | 19 |
| Bevy: `crates/bevy_pbr/src/render/mesh.rs` | 17 |
| Bevy: `crates/bevy_scene/src/lib.rs` | 285 |
| Bevy: `crates/bevy_ui_render/src/lib.rs` | 26 |
| Bevy: `examples/3d/3d_shapes.rs` | 1 |
| Bevy: `examples/3d/motion_blur.rs` | 4 |
| Bevy: `examples/stress_tests/many_morph_targets.rs` | 1 |
| Bevy: `tests/3d/test_invalid_skinned_mesh.rs` | 1 |
| Zed: `crates/client/src/client.rs` | 17 |
| Zed: `crates/editor/src/editor.rs` | 8 |
| Zed: `crates/git_ui/src/git_graph.rs` | 62 |
| Zed: `crates/gpui/src/platform.rs` | 19 |
| Zed: `crates/gpui/src/window.rs` | 46 |
| Zed: `crates/gpui_windows/src/platform.rs` | 3 |
| Zed: `crates/language/src/language.rs` | 5 |
| Zed: `crates/language/src/language_registry.rs` | 1 |
| Zed: `crates/project/tests/integration/project_tests.rs` | 32 |
| Zed: `crates/sqlez/src/thread_safe_connection.rs` | 6 |

## Retained evidence

Evidence lives beneath `.artifacts/analysis/parser-diagnostics-20261017-r1/`:
`rust-native-ast-r1/` retains exact edition/compiler commands, hashes and compressed
unexpanded ASTs; `rust-native-items-r2/` retains the authoritative current comparison;
`rust-native-items-r1/` and `rust-closure-recovery-profile-r1.txt` retain the interrupted
performance diagnosis; `rust-native-controls-r3/` retains the final native controls;
`rust-syntax-full-replay-r1/` retains complete canonical before/after payloads and
source bindings; and `rust-additional-recovery-native-r1/` covers the extra Zed fixture.
The preflight runs Semgrep outside the sandbox. The full gate result, examined log
hashes, source bindings and admission evidence are retained in
`rust-syntax-validation-receipt-r1.json` before successful temporary gate files are
cleaned. Main, the original campaign and original corpus remain unchanged. The full
parser-fix objective remains open, including these extraction defects and the other
languages' outstanding diagnostics.
