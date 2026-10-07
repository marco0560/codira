# Issues 70 and 54 architecture-report closeout

Status: complete. All six implementation slices are complete. Published squash: `107f522`.

Delivered JSON facets and the architecture-report model, DOT/optional SVG,
Markdown, statistics, cycles, violations, hotspots and agent summary, together
with read-only MCP retrieval surfaces. The final recorded repository gate
reported 794 passed, one skipped and 86% coverage, with focused tests,
index/audit, strict docs and generated catalog checks.

Current behavior is documented in [architecture reports](../architecture/architecture-report.md)
and [the MCP guide](../mcp.md).

## Published squash-message correction

The published squash commit `107f522 feat: add architecture reports and
read-only MCP retrieval` contains shell-substituted prose in its body. The
implementation is unaffected. The intended terms are:

- the renamed command is `codira arch`, not `x86_64`;
- the read-only MCP retrieval tools are `emb` and `docs`;
- the validator recovery command is `ruff check . --fix`.

Keep published history intact. Enter long commit messages through an editor
or a quoted message file; never interpolate Markdown backticks through a shell.

## Full execution record

The approved decisions, implementation plan and detailed evidence remain in Git
at the pre-cleanup snapshot. Recover this document's complete ledger with:

```bash
git show f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42:docs/process/issue-070-json-facets-architecture-report-execution-ledger.md
```

This closeout replaces the completed execution plan after the operator-approved
2026-10-07 cleanup. It does not authorize new implementation or external actions.
