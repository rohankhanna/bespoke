# ADR 0005: Treat vocabulary as concept capture, not word collection

## Status
Accepted

## Context
The current discovery pipeline has been improved mechanically by removing obvious junk term extraction, but that only addresses surface noise. The repo is not trying to collect arbitrary words. It is trying to collect concepts that matter for AI-system design, compatibility reasoning, and eventual assembly/planning.

A concept can appear in many linguistic forms:
- normalized topic slug: `claude-code`
- title case phrase: `Claude Code`
- descriptive phrase: `Agent Evaluation`
- alias or near-synonym: `agentic coding`, `AI coding`, `coding agent`
- provider/platform scoped form: `GitHub Actions`, `Anthropic`, `OpenAI`

If the pipeline treats vocabulary as raw accepted strings, then it will either:
- over-admit junk via loose extraction, or
- over-constrain useful concepts via brittle regex rules

The right abstraction is concept-first:
- a concept has one canonical identity
- many observed surface forms can map to that identity
- source evidence should be preserved per observation
- acceptance should be based on whether an observation is evidence of a concept, not whether a token merely “looks like a word”

## Decision
Adopt a concept-first vocabulary pipeline with these principles:

1. The primary unit is a concept record, not a term string.
2. Observed strings are evidence/aliases/forms of a concept, not the concept itself.
3. Discovery should preserve the source observation separately from canonicalization.
4. Mechanical filtering is still allowed, but only as a guardrail against obvious noise; it must not be the main semantic definition of vocabulary.
5. The pipeline should support multiple linguistic forms of the same concept:
   - slug
   - title phrase
   - alias
   - provider-qualified form
   - workflow/process label
6. Concept acceptance should be shaped by concept classes, not just token appearance.

## Initial concept classes
The pipeline should evolve toward at least these concept classes:
- provider/platform
- model family
- tool/component
- workflow/process
- capability
- evaluation/benchmark
- infrastructure/runtime

## Consequences
### Positive
- Better fit for the actual product goal: reasoning about systems and compatibility
- More resilient to surface-form variation
- Easier alias handling and canonicalization
- Better future compatibility-map inputs

### Negative
- Requires a more explicit schema than today’s flat term artifacts
- Requires a candidate/observation layer before accepted concept records
- Requires deliberate canonicalization rules instead of only local string cleanup

## Near-term implementation direction
1. Preserve current junk filtering as a guardrail only.
2. Introduce concept observations as a distinct layer from accepted concepts.
3. Add canonical concept records with aliases and evidence sources.
4. Classify concepts by concept class before using them as downstream planning inputs.
5. Migrate current `terms/` behavior toward concept-oriented artifacts rather than treating each accepted string as final vocabulary truth.
