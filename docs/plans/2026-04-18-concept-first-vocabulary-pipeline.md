# Concept-First Vocabulary Pipeline Plan

> For Hermes: use this plan before implementing further vocabulary-pipeline changes. The repo should collect concepts with evidence, not merely accepted strings.

Goal: reshape vocabulary discovery so the dataset represents concepts, aliases, and evidence rather than a bag of words.

Architecture: split vocabulary into at least two layers: observed concept evidence and accepted canonical concepts. Keep mechanical string filters only as obvious-noise guards, then build concept canonicalization and classification from observed forms and source evidence.

Tech stack: Python discovery script, GitHub-native discovery artifacts on `data`, markdown docs/ADR, JSON records.

---

## Phase 1: Model the data we actually want

### Task 1: Define concept record schema
Objective: write the target shape for a canonical concept artifact.

Files:
- Create: `docs/plans/2026-04-18-concept-first-vocabulary-pipeline.md` (this plan)
- Next implementation target: `docs/adr/0005-concept-first-vocabulary-pipeline.md`

Deliverable schema draft:
- `concept_id`
- `canonical_name`
- `concept_class`
- `aliases[]`
- `observed_forms[]`
- `evidence[]`
- `first_seen_at`
- `last_seen_at`

### Task 2: Define observation schema
Objective: separate raw observed evidence from accepted concepts.

Target fields:
- `observed_text`
- `normalized_form`
- `source_repo`
- `source_file`
- `discovered_via`
- `observation_kind`
- `observed_at`

Observation kinds should include at least:
- `repo-topic`
- `workflow-name`
- later maybe `heading`, `manifest-name`, `component-reference`

---

## Phase 2: Restrict and improve sources

### Task 3: Enumerate allowed concept-evidence sources
Objective: document which GitHub-native surfaces are allowed to contribute concept observations.

Initial allowed sources:
- repository topics
- selected workflow names
- selected manifest/package names

Explicitly excluded for now:
- raw inline code spans
- arbitrary markdown fragments
- tables/example prose without a concept-oriented extractor

### Task 4: Add source-specific extractors
Objective: use extraction logic that knows what kind of concept each source tends to provide.

Examples:
- repo topics -> likely slug aliases / concept candidates
- workflow names -> likely workflow/process concepts
- package names -> likely tool/component concepts

---

## Phase 3: Canonicalize concepts rather than accept strings blindly

### Task 5: Add canonicalization rules
Objective: convert observed forms into canonical candidate identities.

Rules should favor:
- lowercase slug normalization for identity keys
- alias retention instead of alias deletion
- concept-class-aware canonical forms

### Task 6: Add alias grouping
Objective: merge multiple observed forms into one concept when evidence supports equivalence.

Examples to support later:
- `Claude Code` / `claude-code`
- `GitHub Actions` / `github-actions`
- `agent evaluation` / `Agent Evaluation`

---

## Phase 4: Classify concepts

### Task 7: Add concept classes
Objective: prevent mixed semantics inside one flat term pool.

Initial classes:
- provider/platform
- tool/component
- workflow/process
- capability
- evaluation/benchmark
- infrastructure/runtime

### Task 8: Route observations by class
Objective: use source-aware defaults to infer likely concept class, with room for later refinement.

---

## Phase 5: Migrate artifacts

### Task 9: Introduce concept artifact directories
Objective: stop treating `terms/` as the final vocabulary truth.

Likely future layout:
- `data/discovery/concept-observations/*.json`
- `data/discovery/concepts/*.json`
- optional legacy compatibility layer for `terms/`

### Task 10: Preserve backward compatibility temporarily
Objective: avoid breaking the current pipeline abruptly while shifting toward concept-first artifacts.

---

## Phase 6: Verification

### Task 11: Quality checks
Objective: verify that concept artifacts are semantically cleaner than current terms.

Checks:
- no markdown/table/file-pattern junk
- concept aliases grouped, not duplicated blindly
- evidence retained per concept
- source surfaces remain GitHub-native only

### Task 12: Downstream readiness check
Objective: confirm the resulting concept dataset is suitable input for later work on:
- vocabulary pipeline documentation
- compatibility map schema
- requirements/planning system

---

## Immediate next implementation order
1. add observation schema + concept schema docs
2. introduce concept-class-aware extraction paths
3. add canonicalization/alias grouping
4. write concept artifacts to `data`
5. then decide whether legacy `terms/` should remain or become a derived compatibility output
