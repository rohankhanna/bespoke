# Artifact-Domain Branch Model

This document defines a target branch/domain model for machine-written data in bespoke during and after the current prototyping phase.

## Goal

Preserve these invariants:
- artifact ownership is explicit
- jobs are constrained by artifact-domain ownership
- multiple jobs may share one branch/domain only if they are serial and operate within that same ownership boundary
- any branch/domain `Bi` should be rebaseable onto any other branch/domain `Bj` without human conflict handling
- the system should optimize for pairwise mechanical rebaseability, not manual merge workflows

## Core Principle

The right unit is not "one workflow per branch".
The right unit is:
- one artifact domain per branch

A branch/domain may have multiple jobs if:
- they write only that domain's owned paths
- they run serially or otherwise avoid write races
- they preserve deterministic state transitions for that domain

## Domain Types

### 1. Canonical substrate domain

This is the evidence + symbolic truth layer.

Owned artifact families:
- `data/frontier/`
- `data/discovery/repos/`
- `data/discovery/terms/`
- `data/discovery/components/`
- `data/discovery/concepts/`
- `data/discovery/concept-observations/`
- `data/discovery/edges/`
- `data/discovery/indexes/` when they are canonical symbolic indexes
- canonical run summaries for discovery and metadata refresh

Allowed jobs:
- seeded discovery
- metadata refresh
- whole-corpus normalization / migration
- explicit pruning / hygiene jobs that are declared to own canonical substrate maintenance

Properties:
- this is the source domain for prototype inputs
- this domain must remain as stable and explainable as possible
- schema changes here are high-cost and should be deliberate

### 2. Derived browse domain

This is the human-browse / static navigation layer.

Owned artifact families:
- `data/derived/discovery-pages/`
- browse-only run summaries if separated later

Allowed jobs:
- page generation
- browse-layer regeneration
- markdown/static rendering jobs

Properties:
- fully derived from canonical substrate
- disposable/regenerable
- should never be the only copy of important knowledge

### 3. Prototype / experiment domain

This is the experimental learning layer.

Owned artifact families (proposed future shape):
- `data/prototypes/`
- `data/derived/pattern-learning/`
- `data/derived/embeddings/`
- `data/derived/clusters/`
- `data/derived/pattern-candidates/`
- `data/derived/evaluations/`

Allowed jobs:
- embedding generation
- clustering
- unsupervised structure learning
- pattern-candidate induction
- experiment evaluation/comparison

Properties:
- may have multiple competing paths coexisting
- should not mutate canonical substrate truth directly
- should be easy to discard, rerun, compare, and promote from

## Current Recommended Branch/Domain Shape

### Near-term practical model

While the repo still uses a single live `data` branch, model ownership conceptually as:
- substrate families
- browse families
- prototype families

And constrain workflows accordingly.

Current workflow fit:
- `github-seed-discovery-dev` -> canonical substrate domain only
- `github-seed-discovery-nightly-long` -> canonical substrate domain only
- `github-seed-discovery-nightly-followup` -> canonical substrate domain only
- `github-repo-metadata-refresh` -> canonical substrate domain, then derived browse regeneration
- `github-discovery-pages-daily` -> derived browse domain only

This already improves ownership separation even before introducing more physical branches.

## Future Branch Split Recommendation

If and when physical multi-data-branch separation is introduced, prefer branch/domain names like:
- `data-substrate`
- `data-browse`
- `data-prototypes`

### `data-substrate`
Owns only canonical substrate families.

### `data-browse`
Owns only browse-layer outputs derived from substrate.

### `data-prototypes`
Owns prototype and experiment outputs.

## Why Pairwise Rebaseability Becomes Plausible

The rebaseability invariant becomes realistic when one of these is true:

1. Disjoint path ownership
- best and safest case
- branches never edit the same files

2. Same-path deterministic recreation
- possible but fragile
- only acceptable when one branch can recreate identical output mechanically from canonical inputs

3. Temporary composition through regeneration
- rebase onto another branch/domain
- regenerate owned outputs
- no human conflict handling required

The preferred strategy is always:
- disjoint path ownership first

## What "upstream" means here

This document does not use "upstream" in the Git remote-tracking sense.
It means semantic dependency direction.

Example:
- browse domain depends on substrate domain
- prototype domain depends on substrate domain

That means:
- substrate is semantically prior
- browse/prototype outputs can be regenerated after rebasing onto a newer substrate state

This is dependency direction, not a required host/remote pointer configuration.

## Hard Rules For Pairwise Rebaseability

1. No artifact family may have ambiguous ownership.
2. A job may only write paths owned by its domain.
3. If two jobs need the same paths, they belong to the same domain or the path split is wrong.
4. Schema migrations on canonical substrate should be handled by explicit whole-corpus migration jobs, not assumed to propagate automatically through bounded jobs.
5. Derived domains should be rebuildable from canonical inputs.
6. Prototype domains should consume canonical inputs but should not silently rewrite canonical truth.
7. Rebaseability must be judged mechanically, not by hope or low observed conflict frequency.

## Prototype-Phase Guidance

During the current prototype phase:
- treat a pinned canonical substrate snapshot as the experiment input
- allow the live remote substrate to keep growing in the background
- do not change prototype-relevant substrate schema mid-round unless a deliberate migration job is run first
- keep prototype outputs in their own clearly labeled artifact space
- do not let experimental outputs silently redefine canonical concept/component truth

## Immediate Next Steps

1. Keep using conceptual domain separation now, even on the current unified `data` branch.
2. Add explicit artifact-family ownership notes to new workflows and new derived directories.
3. Introduce a dedicated prototype artifact root before first serious unsupervised-learning experiments.
4. Add a branch/domain rebaseability verification plan before introducing multiple physical data branches.
5. Only split into multiple physical data branches once path ownership is explicit enough that pairwise rebaseability is credible.

## Decision Standard

A proposed new data-writing job should be accepted only if it answers clearly:
- what artifact family does it own?
- is that family canonical, derived, or prototype?
- does it overlap any existing domain?
- if so, why is that overlap safe?
- if rebased against any sibling branch/domain, why would no human conflict handling be needed?
