# ADR 0006: Ground the vocabulary pipeline in an English concept ontology, not only string filters

## Status
Accepted

## Context
The vocabulary pipeline is now moving away from collecting arbitrary strings and toward collecting concepts with aliases and source evidence. The next requirement is broader: the system should start from the structure of the English language itself, categorize words and phrases cleanly, and build a map of the buckets that concepts can occupy.

This matters because:
- a concept is not just a word
- a concept can appear as a word, phrase, slug, title, label, or alias
- a word can be polysemous (multiple meanings)
- a concept can belong to multiple buckets at once
- some parts of English are effectively stable over very long periods and should be seeded explicitly rather than rediscovered noisily
- other parts of the ontology must remain open to new and growing entities

The current discovery system still needs mechanical string hygiene, but that must be subordinate to a richer language-aware structure.

## Decision
Adopt an English-grounded concept ontology with two major layers:

1. Base language layer
   Stable English-language entities that should be seeded directly, especially closed-class categories whose membership changes slowly or negligibly over long periods.

2. Open concept layer
   Product-domain and world-domain concepts that can grow over time and be populated from GitHub-native evidence.

## Language-layer categories
The system should explicitly model at least these language-oriented buckets:
- preposition
- conjunction
- determiner/article
- pronoun
- quantifier
- modal/auxiliary
- discourse marker
- interrogative
- negation marker
- deictic/spatial-temporal marker

These categories are not the same as product concepts, but they provide a stable lexical substrate and make later phrase/concept analysis more principled.

## Open concept buckets
The system should also maintain higher-level concept buckets that can accept one or more memberships per concept:
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

A concept may appear in more than one bucket.
Examples:
- "Claude Code" can be both tool/component and workflow/process depending on usage
- "benchmark" can be evaluation/benchmark and workflow/process
- "before" can be a preposition, discourse marker, and temporal relation marker depending on context

## Polysemy and ambiguity
The ontology must support:
- multiple senses per observed form
- multiple buckets per concept
- deferred disambiguation when evidence is insufficient

This means the system should not assume one string equals one concept.

## Seed strategy
Seed the system with stable English closed-class entities first, especially prepositions and other long-stable English function-word classes, and keep that seed distinct from discovered open concepts.

## Consequences
### Positive
- more principled concept modeling
- better handling of aliases, phrase forms, and polysemy
- clearer separation between stable language substrate and evolving domain concepts
- better future compatibility-map and planning inputs

### Negative
- requires a richer schema than flat term lists
- requires concept/bucket modeling work before downstream product logic can fully rely on vocabulary
- requires keeping seeded language entities separate from discovered domain entities

## Near-term implementation direction
1. Create a seeded English closed-class lexicon.
2. Create a concept-bucket map that supports multi-membership.
3. Separate language-layer entities from discovered open concepts.
4. Introduce concept observations and concept records with possible multiple bucket memberships.
5. Preserve room for sense/meaning expansion over time.
