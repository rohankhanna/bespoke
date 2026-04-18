# English-Grounded Vocabulary Foundation Plan

> For Hermes: use this plan before implementing concept-bucket and seeded-language changes. Vocabulary should model concepts, buckets, aliases, and ambiguity, not just accepted strings.

Goal: establish a language-aware foundation for the vocabulary pipeline by seeding stable English closed-class entities and defining a bucket map for open concepts that supports multi-membership and polysemy.

Architecture: create a stable seeded language layer and a separate open concept layer. The language layer should contain long-stable English entities such as prepositions and other closed-class items. The open concept layer should classify discovered concepts into multiple possible buckets with room for aliases and multiple senses.

Tech Stack: markdown ADRs/plans, JSON seed data, Python discovery pipeline, GitHub-native discovery artifacts on `data`.

---

## Phase 1: Seed the stable English layer

### Task 1: Create closed-class seed artifact
Objective: write a machine-readable seed containing stable English function-word categories.

Files:
- Create: `vocabulary/english/stable-closed-classes.json`

Include at least:
- prepositions
- conjunctions
- articles/determiners
- pronouns
- quantifiers
- modals/auxiliaries
- discourse markers
- interrogatives
- negation markers
- deictic markers

### Task 2: Keep the seed separate from discovered concepts
Objective: ensure the system can distinguish between seeded language entities and discovered domain concepts.

Likely artifact metadata:
- `seed_kind: stable-closed-class`
- `language: en`
- `historical_stability: long-stable`

---

## Phase 2: Define concept buckets

### Task 3: Create concept bucket map
Objective: define the buckets in which open concepts can fall, allowing multiple memberships.

Files:
- Create: `vocabulary/concept-buckets.json`

Initial buckets:
- provider/platform
- model family
- tool/component
- workflow/process
- capability
- evaluation/benchmark
- infrastructure/runtime
- governance/policy
- data/document artifact
- language-layer entity

### Task 4: Support multi-membership
Objective: make it explicit that one concept may belong to more than one bucket.

---

## Phase 3: Support ambiguity and multiple meanings

### Task 5: Introduce sense-aware concept thinking
Objective: document that one observed form may map to multiple concepts/senses.

Examples:
- `before` can be preposition, discourse marker, or temporal relation marker
- `benchmark` can be evaluation concept or workflow/process concept

### Task 6: Add deferred disambiguation support
Objective: avoid forcing a single meaning when evidence is insufficient.

---

## Phase 4: Connect the seed to the discovery pipeline

### Task 7: Decide how seeded entities appear in data artifacts
Objective: choose whether seeded language entities live in their own directory or in concept artifacts with special metadata.

### Task 8: Route discovered concepts into buckets separately from seeded entities
Objective: keep the stable language substrate distinct from discovered domain observations.

---

## Phase 5: Migration path

### Task 9: Move from flat term artifacts toward concept records
Objective: keep current discovery useful while evolving to a richer concept model.

### Task 10: Preserve backward compatibility temporarily
Objective: do not break current tooling abruptly while introducing seeded language and concept-bucket artifacts.

---

## Immediate next implementation order
1. create seeded English closed-class dataset
2. create concept bucket map with multi-membership support
3. document ambiguity/polysemy handling
4. wire future concept records to use both seeded language entities and discovered concept evidence
