# ADR-001 — Rank-based Multi-Channel Retrieval (RRF)

**Date:** 24/03/2026
**Status:** Accepted

## Context

The initial retrieval pipeline used a score-based merge across channels (e.g., symbol, semantic). Each channel produced scores that were directly compared during merging.

This approach led to instability and conceptual issues:

* Scores from different channels were not comparable (different scales, distributions, semantics).
* Attempts to normalize or weight scores resulted in fragile, hard-to-tune behavior.
* The semantic channel was implemented as a transformation of symbol results, not as an independent retrieval strategy.
* As a result, semantic contributed little to recall and could not influence ranking meaningfully.

At the same time, the system evolved toward a multi-channel architecture, where different retrieval strategies should contribute independently.

## Decision

Adopt a rank-based merge strategy using **Reciprocal Rank Fusion (RRF)** and redefine channels as independent retrieval mechanisms.

Specifically:

* Replace score-based merging with RRF:

  * Final ranking is computed as:
    `RRF score = Σ (1 / (rank + 1))` across channels.
  * Raw scores are no longer used for cross-channel comparison.

* Redefine channels:

  * Each channel is responsible for **retrieving and ranking its own candidates**.
  * Channels must be **independent** (no longer layered or derived from each other).

* Refactor semantic channel:

  * Remove dependency on `_retrieve_symbol_candidates`.
  * Query the database (`symbol_index`) directly.
  * Use heuristic scoring based on name, module, and (if available) docstring.

* Preserve provenance:

  * Keep per-channel scores for explain/debug purposes.
  * Remove the “winner” concept, which is no longer meaningful under RRF.

## Rationale

This decision resolves the fundamental mismatch between:

* **Channel-local scoring** (confidence within a channel)
* **Global merging** (ordering across channels)

Score-based fusion attempted to use a single value for both purposes, which is not valid when channels use different scoring models.

Rank-based fusion:

* Eliminates the need for score normalization
* Is robust to scale differences
* Naturally rewards agreement across channels
* Is deterministic and simple

Making channels independent ensures that:

* Each channel can introduce new candidates
* The system gains recall, not just re-ranking
* Future channels (e.g., structural, embeddings) can be added without redesign

## Consequences

### Positive

* Stable and predictable ranking behavior
* Improved recall through semantic channel diversification
* Clean architectural separation between channels
* Easier extension with new retrieval strategies
* No need for fragile score calibration

### Negative

* Raw scores lose meaning as global ranking signals
* Explain output no longer has a simple “winner” concept
* Semantic channel currently performs a full scan (may need optimization later)

### Neutral / Trade-offs

* Provenance still exposes scores, but only for inspection
* Ranking logic is now slightly less intuitive without understanding RRF

## Notes

* Future improvements:

  * Optimize semantic retrieval (indexing, filtering)
  * Incorporate docstring indexing more efficiently
  * Introduce additional channels (e.g., structural, embedding-based)
  * Possibly expose RRF contributions in explain output

* This ADR marks the transition from:

  * **single-pipeline scoring system**
    to
  * **true multi-channel retrieval architecture**
