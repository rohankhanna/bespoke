# Prototype Data Pipeline Layer Model

This document defines the prototype data pipeline as a set of layers and explicitly labels which layers can safely run incrementally from prior state and which layers are only trustworthy when rebuilt end-to-end.

## Core distinction

There are two very different update modes:

1. Incremental / delta-safe
- can process only newly added or changed inputs
- can still produce a valid result if prior state is trusted
- usually append-only, monotonic, or mergeable by key

2. Full-rebuild / end-to-end valuable
- should be recomputed across the whole pinned corpus to be trustworthy
- partial recomputation would bias the result or make comparisons invalid
- usually depends on global distributions, corpus-wide co-occurrence, clustering, centroids, graph topology, or thresholds learned from the whole corpus

## Design rule

If an artifact depends on global corpus statistics or latent structure, treat it as full-rebuild.
If an artifact is just canonical normalization or keyed aggregation over local inputs, it is often delta-safe.

## Layer model

### Layer 0 — Canonical substrate snapshot

Inputs:
- `data/discovery/repos/*.json`
- `data/discovery/terms/*.json`
- `data/discovery/components/*.json`
- `data/discovery/concepts/*.json`
- `data/discovery/concept-observations/*.json`
- `data/discovery/indexes/*.json`
- `data/derived/embedding-units.jsonl`

Purpose:
- fixed prototype corpus
- source of truth for round-1 preprocessing

Update mode:
- not part of prototype recomputation
- pinned snapshot only

Rationale:
- this layer is the chosen experiment input, not something we should mutate while comparing paths

---

### Layer 1 — Canonical normalization tables

Proposed artifacts:
- `repo-records.jsonl`
- `concept-table.jsonl`
- `observation-table.jsonl`
- `component-table.jsonl`

Purpose:
- flatten canonical substrate into row-oriented tables
- remove repeated parsing logic from downstream experiments

Update mode:
- delta-safe in principle
- full rebuild preferred for prototype reproducibility

Why delta-safe:
- each output row corresponds to one canonical input object keyed by repo/concept/observation/component identity
- changed source object -> rewrite corresponding row

Why full rebuild still preferred for round 1:
- simpler to verify
- guarantees stable ordering and count accounting
- eliminates hidden stale rows during early experimentation

Recommendation for prototype round 1:
- full rebuild

Recommendation later at scale:
- delta-safe if row replacement is deterministic and manifest counts are revalidated

---

### Layer 2 — Incidence structures

Proposed artifacts:
- `repo-concept-incidence.jsonl`
- `repo-component-incidence.jsonl`

Purpose:
- map repo -> concepts
- map repo -> components

Update mode:
- delta-safe in principle
- full rebuild preferred initially

Why delta-safe:
- each repo row can be recomputed from one repo's local evidence
- repo identity is a natural stable key

Why full rebuild still useful now:
- early prototypes should avoid uncertainty about dropped/renamed concepts/components
- easier to compare experiments if all incidence structures come from one full pass over the pinned corpus

Recommendation for prototype round 1:
- full rebuild

Recommendation later at scale:
- delta-safe by repo key, provided canonical concept/component IDs are stable

---

### Layer 3 — Pairwise co-occurrence edges

Proposed artifacts:
- `concept-cooccurrence.jsonl`
- `component-cooccurrence.jsonl`

Purpose:
- weighted concept-pair support across repos
- weighted component-pair support across repos

Update mode:
- incrementally maintainable, but full rebuild preferred for trust

Why incrementally maintainable:
- each repo contributes local pair counts
- global support can be updated by adding/subtracting repo-level contributions

Why this is not trivially delta-safe operationally:
- if any upstream repo-to-incidence row changes, prior pair contributions must be removed and replaced exactly
- implementation gets stateful quickly
- mistakes silently distort support counts

Recommendation for prototype round 1:
- full rebuild

Recommendation later at scale:
- incremental only if repo-level pair contribution ledgers are stored explicitly

---

### Layer 4 — Deterministic symbolic feature views

Proposed artifacts:
- `repo-symbolic-features.jsonl`

Purpose:
- deterministic feature bundle per repo
- common substrate for multiple learning paths

Update mode:
- delta-safe in principle
- full rebuild preferred initially

Why delta-safe:
- each feature row is keyed by repo
- can be regenerated from repo/incidence tables for that repo

Why full rebuild preferred now:
- feature schema will likely evolve during prototyping
- full rebuild ensures no stale vector shape survives

Recommendation for prototype round 1:
- full rebuild

Recommendation later at scale:
- delta-safe by repo key once feature schema stabilizes

---

### Layer 5 — Global frequency / support summaries

Examples:
- concept frequencies
n- component frequencies
- bucket distributions
- language distributions inside prototype subsets

Purpose:
- global descriptive statistics
- support thresholding and pruning inputs

Update mode:
- incrementally maintainable, but should be treated as full-rebuild in prototypes

Why:
- easy to maintain counters incrementally in theory
- but experiment comparison depends on trust and consistency
- these are cheap enough to recompute fully on the pinned corpus

Recommendation for prototype round 1:
- full rebuild

---

### Layer 6 — Graph topology products

Examples:
- connected components
- centrality scores
- community detection seeds
- motif candidates
- compound pattern candidates derived from graph structure

Purpose:
- identify recurring structural neighborhoods and possible reusable patterns

Update mode:
- full-rebuild

Why:
- topology depends on the whole graph
- local changes can alter global graph structure non-locally
- partial updates make experiment comparison unreliable

Recommendation:
- full rebuild only

---

### Layer 7 — Embedding products

Examples:
- concept embeddings
- repo embeddings
- component embeddings
- centroid summaries
- nearest-neighbor structures

Purpose:
- latent semantic geometry
- neighborhood and similarity search

Update mode:
- generally full-rebuild for prototype truth

Why not delta-safe by default:
- model changes affect all vectors
- preprocessing changes affect all vectors
- normalization changes affect all vectors
- downstream comparisons depend on a consistent vector space

What can be incremental later:
- appending new vectors into a fixed already-approved model space
- ANN index refreshes over a fixed vector schema

But for prototype path comparison:
- treat embeddings as full-rebuild artifacts

Recommendation:
- full rebuild

---

### Layer 8 — Cluster assignments

Examples:
- concept clusters
- repo archetype clusters
- component clusters
- pattern-family candidate clusters

Purpose:
- candidate latent structure and family discovery

Update mode:
- full-rebuild

Why:
- cluster assignments are corpus-global
- adding/removing examples can move cluster boundaries for everyone
- changing model or features invalidates earlier assignments

Recommendation:
- full rebuild only

---

### Layer 9 — Pattern candidate artifacts

Examples:
- atomic pattern candidates
- compound pattern candidates
- component bundles
- structural motifs
- pattern-to-component mappings

Purpose:
- proposed learned structure for downstream evaluation

Update mode:
- full-rebuild

Why:
- these are derived from global structure, support thresholds, clustering, or graph analysis
- they should be considered outputs of a whole prototype path, not incremental maintenance products

Recommendation:
- full rebuild only

---

### Layer 10 — Evaluation artifacts

Examples:
- coverage metrics
- coherence metrics
- label quality reports
- path comparisons
- promotion decisions

Purpose:
- judge which prototype path is worth scaling or preserving

Update mode:
- full-rebuild per path run

Why:
- evaluation must reflect the exact run configuration and full output state

Recommendation:
- full rebuild only

## Summary classification

### Safe to treat as delta-capable later
These can be incrementally maintained once schemas stabilize and per-object replacement is reliable:
- canonical normalization tables
- incidence structures
- deterministic per-repo symbolic feature rows
- simple frequency counters

### Should remain full-rebuild for prototypes
These should be rerun end-to-end for trustworthy prototype comparison:
- co-occurrence aggregates (for now)
- graph topology products
- embeddings
- clusters
- pattern candidates
- evaluations

## Prototype round 1 recommendation

For round 1, use a deliberately conservative rule:

- Layers 1–5: full rebuild on the pinned corpus
- Layers 6–10: full rebuild on the pinned corpus

In other words:
- even if some lower layers are theoretically delta-safe,
- do full rebuilds during the first comparison round to maximize trust and minimize hidden state bugs

Only after the first prototype round should we begin promoting some lower layers into delta-capable maintenance flows.

## Why this matters for databases vs embeddings

A useful analogy:

- database-like canonical tables:
  - often delta-safe
  - keyed rows can be inserted/replaced deterministically

- embedding/clustering layers:
  - usually not delta-trustworthy for prototype comparisons
  - they depend on a globally consistent representational space

So the system should behave like this:
- canonical tables may become incremental later
- learned latent products should be treated as full-run artifacts

## Operational recommendation

Implement the preprocessing pipeline in two parts:

1. Base preprocessing stage
- canonical tables
- incidence tables
- deterministic symbolic features
- can later become partially incremental

2. Global analysis stage
- co-occurrence reductions
- embeddings
- clusters
- pattern proposals
- evaluations
- should remain full-run artifacts during prototyping

## Promotion rule

Do not mark a layer delta-safe just because it can be updated incrementally in theory.
Mark it delta-safe only after:
- deterministic replacement semantics are proven
- no hidden stale-state bugs remain
- outputs are identical to full rebuilds under test

Until then:
- prefer full rebuilds for correctness and experiment trust.
