# Embedding and Clustering Foundation Plan

> For Hermes: use this plan before implementing GPU-backed embedding, nearest-neighbor retrieval, or clustering. Keep the concept layer optimized for constant-time lookup, and treat embedding/clustering as a derived layer built from stable concept and observation artifacts.

**Goal:** Turn the concept/observation corpus into an n-dimensional representation layer suitable for retrieval, clustering, and later recommendation/planning.

**Architecture:** Keep a strict separation between source-of-truth symbolic data (`concepts`, `concept-observations`, indexes) and derived numeric data (embeddings, ANN indexes, cluster assignments). Build deterministic export artifacts first, then add GPU embedding generation, then nearest-neighbor/clustering outputs.

**Tech Stack:** Python, PyTorch CUDA, transformer embedding model, JSON/NPY/Parquet-like artifacts, optional FAISS/HNSW later.

---

## Phase 1: Stable export layer

### Task 1: Define embedding-unit schema
Objective: Decide what gets embedded and with which metadata.

Output file:
- `docs/adr/0007-embedding-unit-and-derived-vector-layer.md`

Requirements:
- embedding units may include:
  - canonical concept text
  - aliases
  - sense labels
  - observation text
  - bucket labels
- every unit must have:
  - stable `unit_id`
  - `concept_id`
  - `unit_kind`
  - `text_for_embedding`
  - `metadata`
- keep symbolic source-of-truth separate from vector artifacts

### Task 2: Export deterministic embedding units
Objective: Materialize one stable export artifact from current concept store.

New files:
- `scripts/export_embedding_units.py`
- `data/derived/embedding-units.jsonl` on `data`

Behavior:
- read `data/discovery/concepts/*.json`
- read `data/discovery/concept-observations/*.json`
- emit deterministic sorted units
- no model inference yet

Verification:
- identical input data produces identical export order/content
- every exported row maps back to one concept/observation

## Phase 2: Constant-time symbolic indexes

### Task 3: Add concept indexes for retrieval
Objective: Avoid scanning the whole concept store for common lookups.

New files on `data`:
- `data/discovery/indexes/concepts-by-alias.json`
- `data/discovery/indexes/concepts-by-bucket.json`
- `data/discovery/indexes/observations-by-concept.json`

Why first:
- useful immediately
- also needed later for interpreting cluster results quickly

## Phase 3: GPU embedding generation

### Task 4: Create local GPU embedding job
Objective: Generate vector representations from the exported embedding units.

New files:
- `scripts/build_embeddings.py`
- `docs/adr/0008-local-gpu-derived-vector-jobs.md`

Derived artifacts:
- `data/derived/embeddings/manifest.json`
- `data/derived/embeddings/units.jsonl`
- `data/derived/embeddings/vectors.npy`

Requirements:
- local/manual first, not CI first
- embed in batches on GPU
- record model name, dimensions, batch size, device, timestamp
- never overwrite symbolic artifacts

### Task 5: Add overnight local embedding runner
Objective: Use the desktop GPU overnight without mixing that work into GitHub CI.

New files:
- `scripts/run_local_embedding_night.sh`
- optional cron/systemd instructions in docs

Why local, not GitHub CI:
- long GPU jobs are better suited to the desktop
- easier to iterate on model choice and batch sizing
- avoids bloating CI runtime and risk

## Phase 4: Similarity and clustering layer

### Task 6: Build nearest-neighbor index
Objective: Support similarity lookup and recommendation-style retrieval.

Possible artifacts:
- `data/derived/ann/manifest.json`
- `data/derived/ann/index.faiss` or fallback implementation
- `data/derived/ann/neighbors.jsonl`

Output shape:
- top-k nearest units/concepts per concept
- similarity scores
- model/index provenance

### Task 7: Build first clustering pass
Objective: Group concepts/observations by vector-space proximity plus symbolic constraints.

Possible artifacts:
- `data/derived/clusters/manifest.json`
- `data/derived/clusters/concept-clusters.json`
- `data/derived/clusters/observation-clusters.json`

Guardrails:
- clustering is derived and revisable
- never replace canonical symbolic truth directly with cluster guesses
- clusters should point back to member concept_ids / observation_ids

## Phase 5: Hybrid symbolic + vector reasoning

### Task 8: Use rules and vectors together
Objective: Avoid letting raw vector similarity become the only meaning system.

Approach:
- symbolic buckets constrain candidate comparisons
- seeded language layer remains distinct from domain concepts
- use vector similarity to propose merges/relations, not auto-commit them blindly
- promote suggestions into reviewable artifacts

---

## Recommended implementation order
1. embedding-unit schema ADR
2. deterministic embedding-unit export
3. symbolic indexes
4. local GPU embedding job
5. nearest-neighbor retrieval
6. clustering outputs
7. hybrid merge/recommendation proposals

## What not to do yet
- do not push long GPU embedding jobs into GitHub-hosted CI
- do not replace canonical concepts with clusters automatically
- do not treat embeddings as the source of truth
- do not mix seeded language-layer entities with domain concepts indiscriminately

## Immediate next step
Implement Phase 1 and Phase 2 first:
- deterministic embedding-unit export
- symbolic lookup indexes

Those are useful even before choosing the final embedding model or clustering stack.
