# Issue 20 similarity-index plugins closeout

Status: complete. All 12 recorded slices are complete (2026-08-25).

Delivered backend-neutral similarity-index contracts, core exact search,
FAISS flat/HNSW candidates, durable-vector ownership, profile routing,
lifecycle operations and installer/bundle integration. The coverage audit
records implementation commits `fd8d927` and `a36771e`, operator-journey commit
`2c997d0`, and completion of the final characterization and branch gate.

Current contracts are in [ADR-031](../adr/ADR-031-similarity-index-plugin-family.md)
and [storage backends](../architecture/storage-backends.md). The
[characterization report](issue-020-similarity-index-characterization-2026-08-25.md)
retains the measured corpus and reproduction context. Observed flat/HNSW
recall@10 of 1.0000 on 128 vectors/16 queries is a non-gating observation.

The recorded final gate exited 0 with formatting, mypy, zero Semgrep findings,
pytest, strict docs, installed-wheel rehearsal, catalog, index and audit checks.
[Issue acceptance evidence](https://github.com/marco0560/codira/issues/20#issuecomment-5416660015)
explicitly excludes #59; Qdrant was a separate follow-up. Neither this closeout
nor those synthetic measurements establish general retrieval quality.

## Full execution record

The approved decisions, implementation plan and detailed evidence remain in Git
at the pre-cleanup snapshot. Recover this document's complete ledger with:

```bash
git show f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42:docs/process/issue-020-similarity-index-plugins-execution-ledger.md
```

This closeout replaces the completed execution plan after the operator-approved
2026-10-07 cleanup. It does not authorize new implementation or external actions.
