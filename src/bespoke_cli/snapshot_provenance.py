from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

DEFAULT_SNAPSHOTS_ROOT = Path("runtime/snapshots")


def snapshot_runtime_root(base_runtime_root: Path, snapshot_id: str | None = None) -> Path:
    if not snapshot_id:
        return base_runtime_root
    if base_runtime_root == Path("runtime/prototypes/repo-stripping"):
        return DEFAULT_SNAPSHOTS_ROOT / snapshot_id
    return base_runtime_root


def _git_rev_parse(ref: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", ref],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    value = result.stdout.strip()
    return value or None


def resolve_snapshot_provenance(
    snapshot_id: str | None = None,
    source_data_ref: str | None = None,
    source_data_commit: str | None = None,
) -> dict[str, Any]:
    resolved_ref = source_data_ref
    resolved_commit = source_data_commit
    if snapshot_id and not resolved_ref:
        resolved_ref = snapshot_id
    if not resolved_commit and snapshot_id:
        resolved_commit = _git_rev_parse(snapshot_id)
    if not resolved_commit and resolved_ref:
        resolved_commit = _git_rev_parse(resolved_ref)
    return {
        "source_snapshot_id": snapshot_id,
        "source_data_ref": resolved_ref,
        "source_data_commit": resolved_commit,
    }
