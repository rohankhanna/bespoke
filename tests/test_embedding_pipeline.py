import importlib

import numpy as np

from bespoke_cli.embedding_pipeline import (
    adaptive_cluster_assignments,
    best_cluster_jaccard_summary,
    build_embedding_units,
    build_pattern_report,
    chunk_text,
    cluster_membership_agreement,
    derive_section_rows,
    dominant_cluster_label_overlap,
    export_embedding_units,
    infer_cluster_family,
    model_task_prefix,
    pairwise_model_agreement,
    pairwise_shared_neighbor_agreement,
    probe_preferred_device,
    summarize_clusters,
)
from bespoke_cli.snapshot_provenance import resolve_snapshot_provenance, snapshot_runtime_root


def test_chunk_text_splits_long_text_with_overlap():
    text = "A" * 100 + "\n\n" + "B" * 100 + "\n\n" + "C" * 100
    chunks = chunk_text(text, max_chars=140, overlap=20)

    assert len(chunks) >= 3
    assert chunks[0].startswith("A")
    assert any("B" in chunk for chunk in chunks)
    assert any("C" in chunk for chunk in chunks)


def test_snapshot_runtime_root_uses_snapshot_directory_for_default_root():
    assert snapshot_runtime_root(importlib.import_module("bespoke_cli.embedding_pipeline").DEFAULT_RUNTIME_ROOT, "data-snapshot-round1-prototype").as_posix() == "runtime/snapshots/data-snapshot-round1-prototype"


def test_export_embedding_units_persists_provenance(tmp_path):
    runtime_root = tmp_path / "runtime"
    dataset_root = runtime_root / "minimal-dataset"
    dataset_root.mkdir(parents=True)
    (dataset_root / "file-parts.jsonl").write_text(
        '{"repo_name": "owner/repo", "repo_slug": "owner__repo", "commit": "abc123", "path": "README.md", "part_kind": "documentation", "text": "# Intro\\nHello"}\n'
    )
    provenance = {
        "source_snapshot_id": "data-snapshot-round1-prototype",
        "source_data_ref": "data-snapshot-round1-prototype",
        "source_data_commit": "679a9d9b",
    }

    summary = export_embedding_units(runtime_root=runtime_root, provenance=provenance)

    assert summary["provenance"]["source_snapshot_id"] == "data-snapshot-round1-prototype"
    saved = importlib.import_module("bespoke_cli.embedding_pipeline").load_json(runtime_root / "embedding-units" / "summary.json")
    assert saved["provenance"]["source_data_ref"] == "data-snapshot-round1-prototype"


def test_build_embedding_units_splits_markdown_into_sections():
    file_parts = [
        {
            "repo_name": "owner/repo",
            "repo_slug": "owner__repo",
            "commit": "abc123",
            "path": "README.md",
            "part_kind": "documentation",
            "text": "# Intro\nWelcome\n\n## Install\nDo this\n\n## Usage\nRun that",
        },
        {
            "repo_name": "owner/repo",
            "repo_slug": "owner__repo",
            "commit": "abc123",
            "path": "src/main.py",
            "part_kind": "source",
            "text": "def main():\n    return 'ok'\n",
        },
    ]

    units = build_embedding_units(file_parts, max_chars=40, overlap=5)
    titles = [unit["section_title"] for unit in units]
    paths = [unit["path"] for unit in units]

    assert "Intro" in titles
    assert "Install" in titles
    assert "Usage" in titles
    assert "def main" in titles
    assert "README.md" in paths
    assert "src/main.py" in paths


def test_derive_section_rows_is_source_aware_for_configs_and_code():
    toml_rows = derive_section_rows("manifest", "pyproject.toml", "[project]\nname='demo'\n\n[tool.pytest]\naddopts='-q'\n")
    py_rows = derive_section_rows("source", "src/main.py", "class App:\n    pass\n\ndef main():\n    return 'ok'\n")

    assert any(title == "[project]" for title, _ in toml_rows)
    assert any(title.startswith("class App") for title, _ in py_rows)
    assert any(title.startswith("def main") for title, _ in py_rows)


def test_adaptive_cluster_assignments_separates_part_kinds():
    units = [
        {"part_kind": "documentation", "repo_slug": "a", "path": "README.md", "section_title": "Intro", "chunk_index": 0, "unit_id": "1", "text": "install usage docs"},
        {"part_kind": "documentation", "repo_slug": "a", "path": "docs/guide.md", "section_title": "Usage", "chunk_index": 0, "unit_id": "2", "text": "install usage guide"},
        {"part_kind": "source", "repo_slug": "a", "path": "src/main.py", "section_title": "document", "chunk_index": 0, "unit_id": "3", "text": "def main return"},
        {"part_kind": "source", "repo_slug": "a", "path": "src/cli.py", "section_title": "document", "chunk_index": 0, "unit_id": "4", "text": "def cli parse"},
    ]
    embeddings = np.array([
        [1.0, 0.0],
        [0.95, 0.05],
        [0.0, 1.0],
        [0.05, 0.95],
    ], dtype=np.float32)

    clusters, metadata = adaptive_cluster_assignments(units, embeddings, threshold=0.7)

    assert len(clusters) == 2
    assert metadata["strategy"] == "per-part-kind-agglomerative-average-linkage"
    assert sorted(len(cluster) for cluster in clusters) == [2, 2]


def test_summarize_clusters_extracts_keywords_and_prefixes():
    units = [
        {
            "unit_id": "u1",
            "repo_slug": "owner__repo",
            "repo_name": "owner/repo",
            "commit": "abc",
            "path": "docs/setup.md",
            "part_kind": "documentation",
            "section_title": "Setup",
            "chunk_index": 0,
            "char_count": 20,
            "text": "Install dependencies and setup environment",
        },
        {
            "unit_id": "u2",
            "repo_slug": "owner__repo",
            "repo_name": "owner/repo",
            "commit": "abc",
            "path": "docs/usage.md",
            "part_kind": "documentation",
            "section_title": "Usage",
            "chunk_index": 0,
            "char_count": 20,
            "text": "Usage guide for environment setup and install",
        },
    ]
    embeddings = np.array([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32)

    summaries = summarize_clusters(units, embeddings, [[0, 1]])

    assert summaries[0]["keywords"]
    assert "docs/setup.md" == summaries[0]["exemplar"]["path"]
    assert summaries[0]["top_path_prefixes"][0].startswith("docs/")


def test_pattern_report_uses_cluster_labels(tmp_path):
    units = [
        {"part_kind": "documentation", "section_title": "Setup", "path": "docs/setup.md"},
        {"part_kind": "documentation", "section_title": "Usage", "path": "docs/usage.md"},
    ]
    clusters = [{"label": "install, setup", "size": 2, "part_kind_counts": {"documentation": 2}, "top_path_prefixes": ["docs/setup"]}]

    report = build_pattern_report(units, clusters, {"model_name": "demo", "embedding_count": 2}, runtime_root=tmp_path)

    assert report["dominant_cluster_labels"] == ["install, setup"]
    assert report["pure_part_kind_cluster_counts"]["documentation"] == 1
    assert "documentation-misc" in report["family_counts"]
    assert "dead_letter_queue" in report
    assert "labeled_clusters" in report


def test_infer_cluster_family_recognizes_workflows():
    cluster = {
        "top_path_prefixes": [".github/workflows"],
        "keywords": ["docker", "push"],
        "part_kind_counts": {"automation": 3},
        "top_section_titles": [],
    }
    assert infer_cluster_family(cluster)["family"] == "automation-workflows"


def test_model_task_prefix_supports_bge_and_nomic():
    assert model_task_prefix("nomic-ai/nomic-embed-text-v1.5", "clustering") == "clustering: "
    assert model_task_prefix("BAAI/bge-large-en-v1.5", "clustering").startswith("Represent this text")


def test_probe_preferred_device_auto_falls_back_for_unsupported_capability(monkeypatch):
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    monkeypatch.setattr("torch.cuda.get_device_capability", lambda index: (12, 1))
    monkeypatch.setattr("torch.cuda.get_device_name", lambda index: "NVIDIA GB10")

    probe = probe_preferred_device("auto")

    assert probe["selected_device"] == "cpu"
    assert probe["used_fallback"] is True
    assert probe["cuda_visible"] is True
    assert probe["cuda_device_name"] == "NVIDIA GB10"


def test_probe_preferred_device_auto_uses_cuda_when_supported(monkeypatch):
    monkeypatch.setattr("torch.cuda.is_available", lambda: True)
    monkeypatch.setattr("torch.cuda.get_device_capability", lambda index: (12, 0))
    monkeypatch.setattr("torch.cuda.get_device_name", lambda index: "Supported GPU")

    probe = probe_preferred_device("auto")

    assert probe["selected_device"] == "cuda"
    assert probe["used_fallback"] is False


def test_pairwise_model_agreement_scores_overlap():
    first = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    second = np.array([[1.0, 0.0], [0.85, 0.15], [0.0, 1.0]], dtype=np.float32)

    score = pairwise_model_agreement(first, second, k=1)

    assert score == 1.0


def test_stability_helpers_compare_shared_units():
    unit_ids_small = ["u1", "u2", "u3"]
    unit_ids_large = ["u1", "u2", "u3", "u4"]
    vectors_small = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    vectors_large = np.array([[1.0, 0.0], [0.85, 0.15], [0.0, 1.0], [0.2, 0.8]], dtype=np.float32)

    shared = pairwise_shared_neighbor_agreement(unit_ids_small, vectors_small, unit_ids_large, vectors_large, k=1)

    assert shared == 1.0


def test_cluster_membership_and_label_overlap_helpers():
    units_a = [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}]
    units_b = [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}]
    clusters_a = [
        {"cluster_id": 0, "label": "alpha", "member_unit_ids": ["u1", "u2"], "top_path_prefixes": ["docs/setup", "src/core"]},
        {"cluster_id": 1, "label": "beta", "member_unit_ids": ["u3"], "top_path_prefixes": ["docs/usage"]},
    ]
    clusters_b = [
        {"cluster_id": 0, "label": "alpha", "member_unit_ids": ["u1", "u2"], "top_path_prefixes": ["docs/setup"]},
        {"cluster_id": 1, "label": "gamma", "member_unit_ids": ["u3"], "top_path_prefixes": ["docs/reference"]},
    ]

    assert cluster_membership_agreement(units_a, clusters_a, units_b, clusters_b) == 1.0
    assert dominant_cluster_label_overlap(clusters_a, clusters_b, top_n=2) == 0.3333
    best_match = best_cluster_jaccard_summary(clusters_a, clusters_b)
    assert best_match["average_best_jaccard"] == 1.0
    assert best_match["average_prefix_overlap"] > 0.0
