# Prototyping Bridge Checkpoint

This diagram captures the current prototyping strategy.

Principles:
- treat a specific data-branch snapshot as the fixed experiment input
- let the remote data branch continue growing independently
- test multiple candidate paths against the same pinned corpus
- require useful labeled outputs, not just interesting latent structure
- promote only paths that earn scale
- preserve non-promoted paths as fallback options

Current pinned prototype snapshot:
- pinned dataset head: `679a9d9b5283c3ebf085b0b94d94adad15070ef3`
- captured after the last successful pre-midnight normalization run and before the failed overnight jobs
- repos: 868
- terms: 2096
- components: 3125
- concepts: 2009
- observations: 2764
- pending frontier beyond the snapshot: 425

Artifacts:
- Mermaid source: `docs/architecture/prototyping-bridge-current-state.mmd`
- PNG render: `docs/architecture/prototyping-bridge-current-state.png`
