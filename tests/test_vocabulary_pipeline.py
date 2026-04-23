import json
from pathlib import Path

from bespoke_cli.vocabulary_pipeline import build_concepts, export_vocabulary, extract_observations, infer_concept_class


def test_extract_observations_collects_headings_workflows_and_dependencies():
    file_parts = [
        {
            "repo_name": "owner/repo",
            "path": "README.md",
            "part_kind": "documentation",
            "text": "# Runtime Gateway\n\n## Install\ntext\n\n## Agent Evaluation\ntext\n",
        },
        {
            "repo_name": "owner/repo",
            "path": ".plans/implementation.md",
            "part_kind": "documentation",
            "text": "# 1. Internal Step\n\n## 2a. Modify __init__\n",
        },
        {
            "repo_name": "owner/repo",
            "path": ".github/workflows/tests.yml",
            "part_kind": "automation",
            "text": "name: Tests and Evaluation\n\non:\n  push:\n",
        },
        {
            "repo_name": "owner/repo",
            "path": "package.json",
            "part_kind": "manifest",
            "text": json.dumps({"name": "demo-app", "dependencies": {"openai": "*", "langchain": "*"}}),
        },
    ]

    observations = extract_observations(file_parts)
    observed_texts = {item["observed_text"] for item in observations}
    kinds = {item["observation_kind"] for item in observations}

    assert "Runtime Gateway" in observed_texts
    assert "Agent Evaluation" in observed_texts
    assert "Tests and Evaluation" in observed_texts
    assert "demo-app" in observed_texts
    assert "openai" in observed_texts
    assert "1. Internal Step" not in observed_texts
    assert "markdown-heading" in kinds
    assert "workflow-name" in kinds
    assert "package-name" in kinds or "dependency-name" in kinds


def test_build_concepts_routes_low_confidence_items_to_review(tmp_path: Path):
    observations = [
        {
            "observed_text": "Tests and Evaluation",
            "normalized_form": "tests-and-evaluation",
            "source_repo": "owner/repo",
            "source_file": ".github/workflows/tests.yml",
            "discovered_via": "workflow-name",
            "observation_kind": "workflow-name",
        },
        {
            "observed_text": "Runtime Gateway",
            "normalized_form": "runtime-gateway",
            "source_repo": "owner/repo",
            "source_file": "README.md",
            "discovered_via": "markdown-heading",
            "observation_kind": "markdown-heading",
        },
    ]

    concepts, review_queue = build_concepts(observations, runtime_root=tmp_path)
    statuses = {concept["concept_id"]: concept["status"] for concept in concepts}
    classes = {concept["concept_id"]: concept["concept_class"] for concept in concepts}

    assert statuses["tests-and-evaluation"] == "approved"
    assert classes["tests-and-evaluation"] == "workflow/process"
    assert statuses["runtime-gateway"] == "review_required"
    assert any(item["concept_id"] == "runtime-gateway" for item in review_queue)


def test_export_vocabulary_writes_review_queue_and_manual_decisions(tmp_path: Path):
    runtime_root = tmp_path / "runtime"
    dataset_root = runtime_root / "minimal-dataset"
    dataset_root.mkdir(parents=True)
    rows = [
        {
            "repo_name": "owner/repo",
            "path": "README.md",
            "part_kind": "documentation",
            "text": "# Runtime Gateway\n\n## Agent Evaluation\n",
        },
        {
            "repo_name": "owner/repo",
            "path": ".github/workflows/tests.yml",
            "part_kind": "automation",
            "text": "name: Tests and Evaluation\n",
        },
    ]
    with (dataset_root / "file-parts.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    provenance = {
        "source_snapshot_id": "data-snapshot-round1-prototype",
        "source_data_ref": "data-snapshot-round1-prototype",
        "source_data_commit": "679a9d9b",
    }
    summary = export_vocabulary(runtime_root=runtime_root, max_observations=50, provenance=provenance)

    assert summary["observation_count"] >= 2
    assert summary["concept_count"] >= 2
    assert summary["provenance"]["source_snapshot_id"] == "data-snapshot-round1-prototype"
    assert (runtime_root / "vocabulary" / "review" / "manual-decisions.json").exists()
    assert (runtime_root / "vocabulary" / "review" / "review-queue.json").exists()


def test_infer_concept_class_for_sources():
    assert infer_concept_class("workflow-name", "Release Build", ".github/workflows/release.yml")[0] == "workflow/process"
    assert infer_concept_class("dependency-name", "openai", "package.json")[0] == "tool/component"
