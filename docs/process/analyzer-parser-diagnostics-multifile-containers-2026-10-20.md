# Multi-file test containers — 2026-10-20

## Original input roles

Classification v51 accounts for **214 LLVM multi-file harness containers**, 55 attributed to C and 159 to C++. These are source-owned test bundles split into separate named files before compiler or analysis-tool consumption. They are not single translation units. This is an input-role exclusion, not an analyzer fix, fragment-compilation result or successful whole-harness claim. Extracted fragments remain ungraded; no fragment is counted as an additional original or fix.

The authoritative totals are **3,973 verified fixes, 680 separated inputs and 21,109 open originals** (C 5,551; C++ 15,558), across all 25,762 original files. Fixed-only progress remains 15.42%; fixed plus justified exclusions is 18.06%. The 680 separated inputs comprise 383 deliberately malformed fixtures, 76 future-grammar inputs, seven earlier documented input roles and 214 multi-file containers.

`separated-inputs-v51-r1/` under `.artifacts/analysis/parser-diagnostics-20261017-r1/` exports all 680 paths, original revisions and hashes, language attribution, versions, qualifications and evidence. `by-language-version-repository.csv` and README.md report complete groups. A language standard does not apply to the container itself: its version column explicitly identifies that role and retains recorded source fragment modes. Original harness mode evidence remains present. Previous exports and classifications are immutable.

## Deterministic evidence and holds

A screen found 369 open candidates containing a split-file source harness command. `split-file-container-evidence-r1/` checks parsed source comments, continued RUN commands, distinct safe fragment names, and a comment-only discarded prelude. Original-source uses outside split-file or FileCheck are held. An actual LLVM 22 split-file invocation captures stdout, stderr, exit status and every output file, then verifies every fragment byte against its original source interval. No source RUN shell command or compiler invocation is executed by this procedure.

The initial screen accepted 265 candidates, but a fragment mentioned only in an output position or a sed command did not establish direct compiler consumption. `split_file_direct_consumers_r1.py` and `split-file-container-direct-evidence-r2/` narrow this to 214 by requiring a named source fragment as a direct input to a recognized compiler or analysis-tool command, excluding output arguments. They reuse all raw extraction evidence without rerunning the splitter. Source inspection of lit's substitutions and LLVM's splitter establishes what the original source, temporary directory and separators mean; the receipt records their exact hashes.

All 11 independent controls pass. Positive controls cover ordinary and line-preserving extraction. Negative controls reject original-source compilation or copying, output-only and sed-only mentions, one-part inputs, discarded code, traversal names, duplicate labels and RUN text in a string. The remaining 155 screened originals stay open because their role needs further evidence. No blanket exclusion is applied to split-file markers.

`split-file-container-admission-audit-v51-r1.json` independently checks all original identities, 214 open-to-container transitions, unchanged prior fixes and exclusions, all 25,548 other v50 rows, and fragment bytes reconstructed from original source intervals. The full export independently matches every selected ledger row and grouped count. This classification changes no analyzer source and leaves its validation evidence separate.

The full remediation objective remains active. See the [syntax-intent report](analyzer-parser-diagnostics-syntax-intent-2026-10-20.md) for the preceding 13 deliberate-negative exclusions and their retained failed harness evidence.
