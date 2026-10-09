# Automatic known-target cases

These 75 public cases are generated from the exact Git revisions recorded in
`fixtures.json`: three repositories, five intents, five cases per intent.
The full initial local dataset contains 100 cases; private-repository cases
remain in ignored artifact storage.

Generate through `scripts/build_known_target_dataset.py`; do not hand-edit
derived queries, targets or digests. See the
[benchmark guide](../../../docs/benchmarks/known-target-quality.md) for the
format, source rules, private-data handling, execution, resume and interpretation.
The score measures retrieval of known targets, not exhaustive human relevance.
