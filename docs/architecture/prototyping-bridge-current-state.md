# Prototyping Bridge Checkpoint

This diagram captures the current prototyping strategy.

Principles:
- treat a specific data-branch snapshot as the fixed experiment input
- let the remote data branch continue growing independently
- test multiple candidate paths against the same pinned corpus
- require useful labeled outputs, not just interesting latent structure
- promote only paths that earn scale
- preserve non-promoted paths as fallback options

Current snapshot represented in the diagram:
- data branch head: `a891282d2df2f785b5e37acb5e1889cd4739ce6a`
- repos: 798
- terms: 1868
- components: 2995
- concepts: 1771
- observations: 2275
- pending frontier beyond the snapshot: 390

Artifacts:
- Mermaid source: `docs/architecture/prototyping-bridge-current-state.mmd`
- PNG render: `docs/architecture/prototyping-bridge-current-state.png`
