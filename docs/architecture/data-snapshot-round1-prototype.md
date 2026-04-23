# Data Snapshot: round1 prototype

This document records the frozen rapid-prototyping dataset checkpoint.

Snapshot identity:
- snapshot tag: `data-snapshot-round1-prototype`
- source branch at selection time: `origin/data`
- source commit: `679a9d9b5283c3ebf085b0b94d94adad15070ef3`

Selection context:
- this is the pinned corpus for rapid prototyping
- later growth on `origin/data` is intentionally excluded from the same prototype round
- the working assumption is that later data remains schema-compatible with this checkpoint, so prototype outputs built here should scale without redefining the substrate contract

Pinned corpus counts at selection time:
- repos: 868
- terms: 2096
- components: 3125
- concepts: 2009
- observations: 2764
- pending frontier outside the pinned corpus: 425

Related docs:
- `docs/architecture/prototype-preprocessing-contract.md`
- `docs/architecture/prototyping-bridge-current-state.md`
- `docs/architecture/prototype-data-pipeline-layer-model.md`

Operational rule:
- prototype work should pin to `data-snapshot-round1-prototype`
- live CI discovery continues on `origin/data`
- if a later prototype round needs a new corpus, cut a new snapshot rather than silently moving this one
