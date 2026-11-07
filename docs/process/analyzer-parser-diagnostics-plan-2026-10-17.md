# Analyzer parser diagnostics: investigation and fix plan

Worktree: `.artifacts/worktrees/analyzer-parser-diagnostics`, branch
`fix/analyzer-parser-diagnostics`, based on benchmark source `91c4e07`.
The original analyzer run, main checkout, and active stress campaign are retained.

## Ordered delivery

1. Freeze the 25,762 distinct parser-diagnostic paths from analyzer main-r1.
   Record source digests, analyzer/language selection, error spans, repository
   revisions, harness annotations, and explicit language-version evidence.
2. Separate confirmed intentionally malformed inputs and confirmed unsupported
   future syntax. Publish per-file evidence and a report grouped by language,
   language version, and repository. Directory names and expected semantic errors
   alone do not prove intentional malformed syntax. Uncertain cases remain in
   the investigation set; unknown versions are identified rather than invented.
3. Group remaining cases by reproduced cause, explain concrete missing artifacts,
   and implement analyzer or shared-contract corrections with focused regressions.
   Preserve truthful partial coverage and do not suppress unresolved diagnostics.
4. Replay corrected analysis against the frozen population under a fresh identity.
   Check source/output digests, known declarations/relationships and error cases;
   report residual cases explicitly. Keep original measurements untouched.
5. Advance changed plugin distributions and official bundle pins as required,
   regenerate generated catalogs through their generator, run workflow quality
   checks and the full repository gate in this worktree. Commit coherent phases.

## Completion requirements and risks

Every baseline path must have an evidence-backed disposition. The malformed and
future-syntax report precedes product fixes and includes the language/version/repo
breakdown. Remaining valid-source cases require explanations, fixes and replay
evidence; a narrower sample or merely turning warnings off is insufficient.
Recovered artifacts need known-target evidence, not only a smaller diagnostic
count. Main's Git revision, running benchmark controls, corpus bytes and original
campaign evidence must remain unchanged.

Macro/preprocessor handling, language selection, incomplete grammar support and
blanket artifact withholding are hypotheses to test, not assumed diagnoses.
Material unresolved architecture or recovery-policy choices will be surfaced
after the evidence identifies their consequences. Classification evidence and
replay progress must checkpoint so interrupted work can continue without
discarding completed results.
