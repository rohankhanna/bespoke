# Architecture

## Purpose

bespoke-cli aims to turn a structured requirement set into a runnable AI-capable system harness.

That broader goal depends on a prerequisite discovery substrate: unsupervised-first learning over heterogeneous code and non-code assets so the repo can recover atomic and non-atomic components, concepts, and pattern families before later planning and tailoring try to assemble systems from them.

The system should support three output classes:
- LLM-first harnesses
- hybrid harnesses
- deterministic or non-LLM harnesses

## Top-Level Flow

0. Vocabulary refresh
1. Tool and component catalog refresh
2. Requirement intake
3. Requirement classification
4. Candidate architecture synthesis
5. Component selection and tailoring
6. Harness assembly
7. Verification against requirement contracts
8. Packaging and handoff

## Current implemented vertical slice

The first implemented prototype path is a local substrate-building layer:
- input: GitHub repo names
- capture: shallow clone each repo at current head and record the exact commit
- stripping: retain text-bearing files and classify them into reusable part buckets
- embedding and analysis: derive comparable units for unsupervised-first vocabulary, component, and pattern discovery
- outputs: repo records, file-part records, embedding artifacts, vocabulary artifacts, and local manifests under ignored runtime storage

This slice is intentionally narrow.
It does not yet solve end-to-end harness tailoring.
It exists to give the repo a concrete local path for:
- turning repo names into reproducible content snapshots
- separating documentation, manifests, automation, and source parts before embeddings
- surfacing candidate atomic and non-atomic components, concepts, and pattern families from mixed repo assets
- creating the evidence base that later planner and tailoring stages can depend on

For prototyping, the repo should treat explicit frozen `data` snapshots as experiment inputs while the live `data` branch continues growing under CI in the background.

## Core Subsystems

### 0. Vocabulary Layer

Responsibilities:
- maintain an up-to-date vocabulary of terms needed to describe AI systems, harness patterns, evaluation concepts, deployment shapes, and component capabilities
- track canonical names, aliases, deprecated terms, and relationships between terms
- provide a normalization surface so requirement intake and planning operate on the same language
- support continuous refresh as the AI ecosystem changes

Key outputs:
- controlled vocabulary entries
- alias and synonym maps
- term deprecation and replacement guidance
- planner-facing normalized terminology

### 1. Tool and Component Catalog Layer

Responsibilities:
- maintain an up-to-date catalog of tools, components, services, runtimes, providers, and harness patterns available to the factory
- record capability metadata, constraints, interfaces, and lifecycle status
- distinguish between what is theoretically known in the vocabulary and what is concretely available in the catalog
- refresh automatically through CI rather than relying on manual memory

Key outputs:
- machine-readable catalog entries
- availability and freshness metadata
- compatibility and capability metadata
- planner-facing candidate component sets

### 2. Requirement Contract Layer

Responsibilities:
- accept structured inputs from users or other systems
- separate hard constraints from flexible goals
- capture environment constraints, budget, latency, privacy, deployment targets, and success criteria
- produce a normalized requirement contract

Key outputs:
- normalized requirement document
- validation errors and missing-field prompts
- machine-checkable hard constraints where possible

### 3. Planner / Tailor Layer

Responsibilities:
- map requirement contracts to candidate system designs
- choose between LLM, hybrid, and non-LLM approaches
- decide whether the factory itself should use an LLM for synthesis or stay deterministic
- produce a rationale for why a candidate harness fits the contract

Key outputs:
- one or more candidate architectures
- tradeoff summaries
- explanation of hard-requirement satisfaction and soft-goal optimization

### 4. Compatibility Map Layer

Responsibilities:
- maintain an evidence-backed map of which components, patterns, and environments are compatible
- support mixed certainty levels: graded compatibility for critical surfaces, binary compatibility for medium-importance surfaces, and explicit unknown / known-unknown states for the long tail
- preserve conflicting observations instead of collapsing them prematurely into one truth
- distinguish canonical compatibility assertions from raw user and CI evidence
- make contribution painless enough to become a natural part of community participation rather than a chore

Key outputs:
- compatibility assertions
- scoped compatibility records by environment, version, and deployment shape
- confidence and freshness metadata
- known-unknown inventories
- conflict sets and evidence trails

### 5. Catalog Ingestion and Refresh Layer

Responsibilities:
- ingest vocabulary and catalog sources from GitHub-native surfaces and manually raised PRs only
- do not use web scraping; repository-populated knowledge must come from github.com APIs/content or explicit human submissions through GitHub workflows
- reconcile external updates with local canonical schemas
- mark entries as new, changed, deprecated, unavailable, or unverified
- produce deterministic refresh outputs for the planner and operator
- ingest community and CI compatibility evidence and re-score freshness and confidence over time
- keep refresh cadence policy pluggable: support multiple revisit horizons without hard-coding one permanent schedule model too early

Key outputs:
- refreshed vocabulary snapshots
- refreshed tool/component catalog snapshots
- compatibility evidence snapshots
- change reports for CI runs
- freshness metadata and review queues

### 6. Harness Assembly Layer

Responsibilities:
- materialize a selected design into concrete repo/runtime artifacts
- produce prompts, configs, pipelines, adapters, schemas, tests, and deployment scaffolding
- keep generated artifacts reproducible and reviewable

Key outputs:
- runnable harness package
- generated configs and templates
- operator-facing setup and verification instructions

### 7. Evaluation Layer

Responsibilities:
- verify hard constraints
- score flexible requirements
- run regressions across candidate harnesses
- make tradeoffs visible instead of hidden

Key outputs:
- pass/fail requirement checks
- weighted comparison scores
- regression reports and acceptance summaries

### 8. State and Runtime Layer

Responsibilities:
- persist plans, generated artifacts, evaluation results, and operator decisions
- support safe resume after interruption
- separate version-controlled source from runtime data

Key outputs:
- reproducible state snapshots
- resumable work products
- clear boundary between content and data

## Design Principles

- hard requirements beat optimization goals
- the system must maintain a current vocabulary before it can plan well
- the system must maintain a current catalog of tools and components before it can tailor well
- compatibility knowledge must be evidence-backed, scoped, and able to represent unknowns and conflicts honestly
- vocabulary and catalog refresh should be automated through CI, not dependent on agent memory
- no web scraping: CI-populated knowledge must come from github.com or manually raised PRs only
- community contributions should be painless, low-friction, and part of normal collaboration rather than a chore or paywalled artifact stream
- assume nothing is permanent: providers, models, APIs, runtimes, and integration paths can disappear or degrade
- no single external component should be a hard dependency that makes the system unusable when it disappears
- not every problem should be solved with an LLM
- generated output is data until deliberately adopted as maintained source
- every selected architecture should be explainable
- evaluation is part of the product, not an afterthought
- state and restart safety are first-class concerns

## Candidate Repository Shape

- `schemas/` for requirement and artifact schemas
- `vocabulary/` for controlled terminology, aliases, and term metadata
- `registry/` for tool and component capability metadata
- `compatibility/` for evidence-backed compatibility assertions, observations, and conflict sets
- `ingestion/` for CI-driven refresh jobs and normalization pipelines
- `factory/` for planning, tailoring, and assembly logic
- `evaluators/` for requirement checks and scoring
- `templates/` for emitted harness templates
- `docs/` for ADRs, plans, and architecture diagrams
- `tests/` for contract, planner, registry, compatibility, and end-to-end verification
- `runtime/` or another ignored path for mutable state and generated working data

## Near-Term Decisions To Make

- whether the first implementation is library-first, CLI-first, or service-first
- how requirement contracts are represented on disk
- how vocabulary terms are sourced, normalized, versioned, and deprecated
- how tool/component catalog metadata is sourced, normalized, versioned, and freshness-scored
- what compatibility assertion schema should look like for graded, binary, and unknown states
- how raw community observations enter the compatibility map with low friction while still preserving trust signals
- what trust, confidence, and freshness model should govern conflicting compatibility reports
- what CI cadence refreshes vocabulary and catalog data
- how to review CI-discovered additions, removals, and deprecations before they affect planning
- how to score flexible requirements without obscuring hard failures
- how to package generated harness outputs for human review and deployment
