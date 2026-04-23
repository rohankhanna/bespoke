# Live-Data / Frozen-Snapshot Decoupling Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: let discovery CI run continuously against a live `data` branch while user prototyping, embeddings, clustering, and vocabulary work stay pinned to explicit frozen dataset snapshots.

Architecture: treat `origin/data` as the continuously growing ingestion stream and introduce immutable snapshot refs cut from exact `origin/data` commits. All user-facing prototype work should consume a snapshot ID, never the moving live branch. Derived runtime outputs should be keyed by snapshot ID so experiments stay reproducible while CI continues growing the live corpus.

Tech Stack: git refs/tags, GitHub Actions, Python CLI scripts, deterministic JSON metadata, ignored runtime storage, pytest.

---

### Task 1: Write the snapshot model into repo docs

Objective: define the live-vs-frozen model explicitly before wiring scripts and workflows.

Files:
- Modify: `ARCHITECTURE.md`
- Modify: `docs/architecture/discovery-coverage.md`
- Create or modify: a small architecture note under `docs/architecture/` if needed

Step 1: Document the two data surfaces
- `origin/data` = live CI-owned ingestion stream
- `data-snapshot-*` = frozen analysis/prototyping checkpoints

Step 2: Document the contract
- user dev/prototype work must pin to a snapshot ref
- CI must never rewrite snapshot refs once cut
- post-checkpoint live data must remain schema-compatible unless a new versioned schema family is introduced deliberately

Step 3: Verification
Run: `git diff -- ARCHITECTURE.md docs/architecture/`
Expected: docs clearly distinguish live data from frozen snapshots

### Task 2: Add a snapshot metadata schema and file layout

Objective: make snapshots first-class and inspectable.

Files:
- Create: `schemas/data_snapshot.schema.json`
- Create: `data/snapshots/README.md` or doc-only equivalent if schema lives outside tracked data
- Modify: relevant docs under `docs/architecture/`

Step 1: Define snapshot metadata shape
Fields should include at minimum:
- `snapshot_id`
- `source_ref`
- `source_commit`
- `created_at`
- `schema_family`
- `schema_version`
- `note`

Step 2: Decide storage rule
- metadata may live in a tracked docs/config area on `main`
- actual heavy snapshot corpus remains represented by git ref/tag to an existing `data` commit, not duplicated files

Step 3: Verification
Run: inspect the JSON schema manually and confirm it can describe one frozen dataset without copying the corpus

### Task 3: Create a local snapshot-cut command

Objective: turn the current `origin/data` commit into a frozen, named snapshot intentionally.

Files:
- Create: `scripts/create_data_snapshot.py`
- Test: `tests/test_create_data_snapshot.py`
- Modify: `pyproject.toml` if adding a CLI entrypoint is useful

Step 1: Write failing tests
Cover:
- snapshot name generation or validation
- metadata emission
- refusal to overwrite an existing snapshot unless explicitly forced

Step 2: Implement minimal behavior
Command should:
- resolve the target `origin/data` commit
- create a snapshot tag or local ref like `data-snapshot-YYYY-MM-DDTHHMMSSZ`
- write snapshot metadata
- print the snapshot id and source commit

Step 3: Verification
Run: `pytest -q tests/test_create_data_snapshot.py -v`
Expected: PASS

### Task 4: Prefer tags for immutable snapshots

Objective: make snapshot refs hard to mutate accidentally.

Files:
- Modify: `scripts/create_data_snapshot.py`
- Modify: docs created above

Step 1: Implement default snapshot ref shape as an annotated tag
Suggested pattern:
- `data-snapshot-2026-04-23T0930Z`

Step 2: Record the source commit and note in the tag metadata or companion metadata file

Step 3: Verification
Run: create one local snapshot against current `origin/data`
Expected: `git rev-parse <snapshot-tag>` resolves to the intended `origin/data` commit

### Task 5: Key prototype runtime paths by snapshot id

Objective: stop derived work from silently mixing outputs from different data states.

Files:
- Modify: `src/bespoke_cli/embedding_pipeline.py`
- Modify: `src/bespoke_cli/vocabulary_pipeline.py`
- Modify: any local scripts that read runtime roots
- Test: `tests/test_embedding_pipeline.py`
- Test: `tests/test_vocabulary_pipeline.py`

Step 1: Add a snapshot-aware runtime root convention
Example:
- `runtime/snapshots/<snapshot_id>/...`

Step 2: Make commands accept either:
- explicit snapshot id
- explicit source commit/ref
- or explicit runtime root already containing pinned snapshot metadata

Step 3: Persist provenance into outputs
Every summary/report should include:
- `source_data_ref`
- `source_data_commit`
- `source_snapshot_id`

Step 4: Verification
Run: `pytest -q`
Expected: PASS and summaries include pinned provenance fields

### Task 6: Add a schema-compatibility guard for live data after the checkpoint

Objective: enforce the user's assumption that post-checkpoint live data keeps the same schema.

Files:
- Create or modify: a validation script under `scripts/`
- Modify: `.github/workflows/github-seed-discovery-nightly-long.yml`
- Modify: `.github/workflows/github-seed-discovery-nightly-followup.yml`
- Modify: dev workflow if appropriate
- Test: add focused tests if the validator is Python

Step 1: Define what compatibility means
At minimum:
- required keys stay present
- field meanings do not silently change
- new optional fields are acceptable
- breaking field removals/renames fail validation

Step 2: Add a validation pass in CI
- validate newly written artifacts against the frozen schema contract before push

Step 3: Verification
Run: validator locally against the current `origin/data` shape
Expected: PASS on current live data

### Task 7: Add a snapshot creation workflow or manual helper path

Objective: let the user deliberately cut prototype checkpoints without stopping ingestion.

Files:
- Create: `.github/workflows/data-snapshot-cut.yml` or keep it local-only initially
- Modify: docs describing the preferred operator flow

Step 1: Keep it manual-first
- `workflow_dispatch` only at first
- one input for optional snapshot note/name

Step 2: Make it non-destructive
- read current `origin/data`
- create snapshot ref + metadata only
- do not rewrite live data

Step 3: Verification
Run: trigger locally or manually once, confirm snapshot metadata/ref is created correctly

### Task 8: Define 24/7 CI batching cleanly

Objective: keep live discovery running continuously without overlapping writer jobs.

Files:
- Modify: long/followup workflows or create two additional lane workflows
- Modify: docs describing the lane schedule and purpose

Step 1: Adopt four daily windows
Suggested pattern:
- 00:00–05:30 UTC equivalent lane
- 06:00–11:30
- 12:00–17:30
- 18:00–23:30
with ~30 minute gaps between lanes

Step 2: Keep one shared concurrency group
- this preserves single-writer safety even if GitHub scheduling jitters

Step 3: Make each lane purpose identical unless later evidence justifies specialization

Step 4: Verification
Run: inspect workflow cron expressions and concurrency groups
Expected: no overlap in intended windows; all share the same single-writer group

### Task 9: Add a local worktree helper for snapshot-based prototyping

Objective: make it easy to work on a frozen corpus without touching the live branch.

Files:
- Create: `scripts/checkout_data_snapshot_worktree.sh` or Python equivalent
- Modify: docs under `docs/architecture/` or `README.md`

Step 1: Build the helper
Input:
- snapshot id/tag
Output:
- a detached worktree or a documented local checkout path pinned to that snapshot

Step 2: Ensure prototype commands can point at that snapshot path or its metadata

Step 3: Verification
Run: helper against one snapshot tag
Expected: worktree resolves to the exact frozen data commit

### Task 10: Record the current rapid-prototyping checkpoint explicitly

Objective: preserve the already-agreed schema-stable checkpoint as the prototype baseline.

Files:
- Use: current agreed `origin/data` commit
- Create: snapshot metadata for that exact checkpoint
- Update: docs to call it out as the rapid-prototyping baseline

Step 1: Identify the exact commit and snapshot name
Step 2: Cut the snapshot ref
Step 3: Record its metadata and mark it as the rapid-prototype baseline

Step 4: Verification
Run: `git rev-parse <snapshot-tag>` and compare to the intended source commit
Expected: exact match

---

Recommended execution order:
1. Task 10 — preserve the current agreed checkpoint
2. Task 1 — document the model
3. Task 3 + Task 4 — snapshot cut command and immutable tag convention
4. Task 5 — snapshot-keyed runtime outputs
5. Task 6 — schema compatibility guard
6. Task 8 — 24/7 CI batching
7. Task 9 — local snapshot worktree helper
8. Task 7 — manual snapshot-cut workflow if still useful after local tooling exists

Why this order:
- first preserve the exact dataset the user already wants as the prototype baseline
- then stop future drift from invalidating that assumption
- only after that scale the live CI cadence more aggressively
