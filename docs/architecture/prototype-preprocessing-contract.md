# Prototype Preprocessing Contract

This document defines the first prototype path over the pinned dataset snapshot.

## Pinned input

Use this exact corpus as prototype input for round 1:
- pinned dataset head: `679a9d9b5283c3ebf085b0b94d94adad15070ef3`

Pinned corpus counts at selection time:
- repos: 868
- terms: 2096
- components: 3125
- concepts: 2009
- observations: 2764
- pending frontier outside the pinned corpus: 425

During this prototype round:
- this pinned snapshot is the experiment input
- later data growth is not part of the same experiment round
- later schema changes do not retroactively change the validity of this prototype input

## Prototype objective

Transform the pinned corpus into a set of derived prototype artifacts that are useful for pattern learning.

The immediate goal is not to solve the whole pattern-learning problem at once.
The immediate goal is to preprocess the corpus into a small number of stable, reusable intermediate products that multiple candidate pattern-learning paths can share.

## Raw vs preprocessed data

The pinned corpus should be treated as canonical substrate input, not as fully raw data.
It is already partially normalized and symbolized.

So for this prototype, think in layers:

### Layer 0: Canonical substrate input
Existing pinned inputs:
- `data/discovery/repos/*.json`
- `data/discovery/terms/*.json`
- `data/discovery/components/*.json`
- `data/discovery/concepts/*.json`
- `data/discovery/concept-observations/*.json`
- `data/discovery/indexes/*.json`
- `data/derived/embedding-units.jsonl`

This is not truly raw web text.
It is already a curated GitHub-native evidence substrate.

### Layer 1: Prototype preprocessing outputs
The first prototype path should derive reusable intermediate components from Layer 0.

## Proposed preprocessing components

The first prototype path should produce these artifact families under a prototype-specific derived root.

Recommended root:
- `data/prototypes/round-1/`

### 1. Repo records for prototype use
Output:
- `data/prototypes/round-1/repo-records.jsonl`

Purpose:
- create one normalized record per repo
- flatten only the fields useful for pattern learning
- stabilize access for downstream experiments

Suggested fields:
- repo_id
- description
- topics
- language
- stars
- archived
- fork
- updated_bucket
- star_bucket
- product_surface_bucket
- counts of terms/components/concepts/observations

### 2. Concept vocabulary table
Output:
- `data/prototypes/round-1/concept-table.jsonl`

Purpose:
- normalize concept-level symbolic entities into one easy-to-consume table
- one row per concept

Suggested fields:
- concept_id
- canonical_name
- aliases
- primary_bucket
- buckets
- ambiguity_status
- definition_status
- gloss_status
- lexical_status
- evidence_count
- observation_count
- source_repo_count

### 3. Observation table
Output:
- `data/prototypes/round-1/observation-table.jsonl`

Purpose:
- normalize observation-level evidence into one row-per-observation dataset
- keep linkage to repo and concept explicit

Suggested fields:
- observation_id
- concept_id
- observed_text
- normalized_form
- discovered_via
- source_repo
- source_file
- candidate_primary_bucket
- candidate_buckets
- source_context_snippet
- source_repo_description

### 4. Component table
Output:
- `data/prototypes/round-1/component-table.jsonl`

Purpose:
- one normalized component row per component artifact
- support component clustering/co-occurrence learning

Suggested fields:
- component_id (slug or file stem)
- component
- source_repo_count
- source_file_count
- discovered_via breakdown if available

### 5. Repo-to-concept incidence matrix
Output:
- `data/prototypes/round-1/repo-concept-incidence.jsonl`

Purpose:
- encode which concepts appear in which repos
- support graph motifs, clustering, and later embedding experiments

Suggested row shape:
- repo_id
- concept_ids[]
- concept_count
- primary_buckets_present[]

### 6. Repo-to-component incidence matrix
Output:
- `data/prototypes/round-1/repo-component-incidence.jsonl`

Purpose:
- encode which components appear in which repos
- support co-occurrence mining and recurring architectural bundle detection

Suggested row shape:
- repo_id
- component_ids[]
- component_count

### 7. Concept co-occurrence graph input
Output:
- `data/prototypes/round-1/concept-cooccurrence.jsonl`

Purpose:
- one edge per concept pair co-occurring within a repo
- weighted by repo support

Suggested row shape:
- source_concept_id
- target_concept_id
- support_repo_count
- shared_buckets[]

### 8. Component co-occurrence graph input
Output:
- `data/prototypes/round-1/component-cooccurrence.jsonl`

Purpose:
- one edge per component pair co-occurring within a repo
- useful for recurring implementation-pattern mining

Suggested row shape:
- source_component_id
- target_component_id
- support_repo_count

### 9. Repo feature vectors (symbolic)
Output:
- `data/prototypes/round-1/repo-symbolic-features.jsonl`

Purpose:
- produce a deterministic feature representation for each repo without yet committing to any specific model family

Suggested fields:
- repo_id
- language_bucket
- product_surface_bucket
- concept_ids[]
- component_ids[]
- updated_bucket
- star_bucket
- top_topics[]

### 10. Prototype manifest
Output:
- `data/prototypes/round-1/manifest.json`

Purpose:
- freeze the prototype contract for this round
- record the exact input head and output artifact set

Suggested fields:
- pinned_data_head
- generated_at
- artifact_paths
- counts per artifact family
- schema version

## Why this preprocessing path first

This path is good because it:
- does not commit to one model family
- supports symbolic-first paths
- supports graph paths
- supports embedding-assisted paths later
- creates reusable intermediate products instead of single-use experiment outputs

So this first path is not the final pattern-learning pipeline.
It is the common preprocessed substrate for multiple candidate paths.

## Candidate next-stage paths enabled by this preprocessing

After this preprocessing exists, we can test at least these paths against the same preprocessed outputs:

1. symbolic / graph-first pattern induction
- concept/component co-occurrence motifs
- compound pattern proposals from recurring bundles

2. embedding-assisted concept grouping
- use repo-symbolic-features + embedding-units to cluster or compare

3. repo archetype clustering
- cluster repo records by symbolic feature vectors

4. component-bundle discovery
- infer recurring implementation bundles from component incidence/co-occurrence

## Minimal success criteria for preprocessing round 1

This preprocessing round succeeds if it produces:
- stable machine-readable tables for repos, concepts, observations, and components
- explicit linkage between repo, concept, and component layers
- reusable co-occurrence inputs
- a manifest that pins exact input and output scope

This preprocessing round does not require:
- final pattern taxonomy
- final ontology
- final model choice
- final clustering choice

## What we should do next

Immediate implementation target:
- add a prototype preprocessing script, probably something like:
  - `scripts/build_prototype_round1_inputs.py`

That script should read the pinned corpus state and write:
- `data/prototypes/round-1/...`

The script should be deterministic and rerunnable.

## Promotion rule

Only after this preprocessing layer exists should we compare candidate pattern-learning paths.

Reason:
- otherwise each path will silently invent its own data representation,
- making fair comparison much harder.
