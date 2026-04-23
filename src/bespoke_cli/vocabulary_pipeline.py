from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bespoke_cli.snapshot_provenance import resolve_snapshot_provenance, snapshot_runtime_root

DEFAULT_RUNTIME_ROOT = Path("runtime/prototypes/repo-stripping")
DEFAULT_MAX_OBSERVATIONS = 1000
REVIEW_CONFIDENCE_THRESHOLD = 0.75
STOP_TERMS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "into",
    "this",
    "that",
    "your",
    "using",
    "used",
    "guide",
    "readme",
    "documentation",
    "docs",
    "issue",
    "issues",
    "pull",
    "request",
    "requests",
    "template",
    "templates",
    "workflow",
    "workflows",
    "python",
    "json",
    "yaml",
    "toml",
}
HEADING_BLACKLIST = {
    "installation",
    "usage",
    "overview",
    "introduction",
    "getting started",
    "requirements",
    "license",
    "contributing",
    "checklist",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def normalize_alias(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().strip("`\"'"))
    return normalized


def split_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9+_.-]*", text)


def infer_concept_class(observation_kind: str, observed_text: str, source_file: str) -> tuple[str, float, str]:
    lowered = observed_text.lower()
    source_lower = source_file.lower()
    if observation_kind == "workflow-name":
        return "workflow/process", 0.95, "workflow name"
    if observation_kind == "dependency-name":
        return "tool/component", 0.95, "manifest dependency"
    if observation_kind == "package-name":
        return "tool/component", 0.9, "package or project name"
    if observation_kind == "repo-topic":
        return "capability", 0.8, "repo topic"
    if observation_kind == "markdown-heading":
        if any(token in lowered for token in ["deploy", "release", "build", "test", "evaluate"]):
            return "workflow/process", 0.8, "heading keywords"
        if any(token in lowered for token in ["agent", "runtime", "server", "memory", "gateway", "tool", "provider"]):
            return "capability", 0.7, "heading keywords"
        return "unclassified", 0.35, "generic heading"
    if source_lower.endswith(("package.json", "pyproject.toml", "requirements.txt")):
        return "tool/component", 0.75, "manifest source"
    return "unclassified", 0.2, "no strong source signal"


def load_manual_review(runtime_root: Path) -> dict[str, Any]:
    review_root = runtime_root / "vocabulary" / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    manual_path = review_root / "manual-decisions.json"
    if not manual_path.exists():
        write_json(manual_path, {"decisions": {}})
        return {"decisions": {}}
    return load_json(manual_path)


def heading_candidates(text: str, source_file: str) -> list[str]:
    matches = re.findall(r"(?m)^#{1,6}\s+(.+)$", text)
    results = []
    source_lower = source_file.lower()
    for match in matches:
        cleaned = normalize_alias(match)
        lowered = cleaned.lower()
        if source_lower.startswith(".plans/"):
            continue
        if lowered in HEADING_BLACKLIST:
            continue
        if len(cleaned) < 4 or len(cleaned) > 80:
            continue
        if re.match(r"^[0-9]+[a-z]?\.", cleaned.lower()):
            continue
        if any(token in cleaned for token in ["(~", "()", "__", "/", "\\"]):
            continue
        if len(split_words(cleaned)) < 2:
            continue
        results.append(cleaned)
    return results


def workflow_name_candidate(text: str) -> str | None:
    match = re.search(r"(?m)^name:\s*[\"']?(.+?)[\"']?\s*$", text)
    if not match:
        return None
    cleaned = normalize_alias(match.group(1))
    return cleaned if cleaned else None


def package_name_candidate(text: str, path: str) -> list[str]:
    path_lower = path.lower()
    names: list[str] = []
    if path_lower.endswith("package.json"):
        try:
            obj = json.loads(text)
        except Exception:
            return []
        if isinstance(obj.get("name"), str):
            names.append(normalize_alias(obj["name"]))
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for dep in (obj.get(section) or {}).keys():
                names.append(normalize_alias(dep))
        return names
    if path_lower.endswith("pyproject.toml"):
        for match in re.findall(r"(?m)^name\s*=\s*[\"']([^\"']+)[\"']", text):
            names.append(normalize_alias(match))
        for match in re.findall(r"(?m)^[A-Za-z0-9_.-]+\s*=\s*[\"'][^\"']+[\"']", text):
            key = normalize_alias(match.split("=", 1)[0])
            if key and key not in {"name", "version", "description", "requires-python"}:
                names.append(key)
        return names
    if path_lower.endswith("requirements.txt"):
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            dep = re.split(r"[<>=!~ ]", line, maxsplit=1)[0].strip()
            if dep:
                names.append(normalize_alias(dep))
        return names
    return []


def topic_candidates(repos_path: Path) -> list[dict[str, str]]:
    repo_rows = load_json(repos_path)
    observations: list[dict[str, str]] = []
    for row in repo_rows:
        repo_name = row["repo_name"]
        slug = row["repo_slug"]
        repo_record_path = repos_path.parent.parent / "discovery" / "repos"
        _ = slug  # placeholder to keep interface stable if runtime discovery data is added later
        observations.append({"repo_name": repo_name, "observed_text": repo_name.split("/", 1)[-1]})
    return observations


def extract_observations(file_parts: list[dict[str, Any]], max_observations: int | None = None) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for record in file_parts:
        repo_name = record["repo_name"]
        path = record["path"]
        text = record["text"]
        part_kind = record["part_kind"]

        if part_kind == "documentation" and (path.lower().startswith("docs/") or Path(path).name.lower().startswith("readme")):
            for heading in heading_candidates(text, path):
                observations.append(
                    {
                        "observed_text": heading,
                        "normalized_form": slugify(heading),
                        "source_repo": repo_name,
                        "source_file": path,
                        "discovered_via": "markdown-heading",
                        "observation_kind": "markdown-heading",
                    }
                )
        if part_kind == "automation" and path.lower().endswith((".yml", ".yaml")):
            workflow_name = workflow_name_candidate(text)
            if workflow_name:
                observations.append(
                    {
                        "observed_text": workflow_name,
                        "normalized_form": slugify(workflow_name),
                        "source_repo": repo_name,
                        "source_file": path,
                        "discovered_via": "workflow-name",
                        "observation_kind": "workflow-name",
                    }
                )
        if part_kind == "manifest":
            for name in package_name_candidate(text, path):
                kind = "dependency-name"
                if path.lower().endswith(("package.json", "pyproject.toml")) and name in text[:200]:
                    kind = "package-name"
                observations.append(
                    {
                        "observed_text": name,
                        "normalized_form": slugify(name),
                        "source_repo": repo_name,
                        "source_file": path,
                        "discovered_via": kind,
                        "observation_kind": kind,
                    }
                )
    deduped: list[dict[str, Any]] = []
    seen = set()
    for obs in observations:
        key = (obs["normalized_form"], obs["source_repo"], obs["source_file"], obs["observation_kind"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(obs)
        if max_observations is not None and len(deduped) >= max_observations:
            break
    return deduped


def build_concepts(observations: list[dict[str, Any]], runtime_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manual_decisions = load_manual_review(runtime_root).get("decisions", {})
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[observation["normalized_form"]].append(observation)

    concepts: list[dict[str, Any]] = []
    review_queue: list[dict[str, Any]] = []
    for normalized_form, group in sorted(grouped.items()):
        observed_forms = sorted({item["observed_text"] for item in group})
        evidence = [
            {
                "source_repo": item["source_repo"],
                "source_file": item["source_file"],
                "discovered_via": item["discovered_via"],
                "observation_kind": item["observation_kind"],
            }
            for item in group
        ]
        representative = max(observed_forms, key=len)
        inferred_class, inferred_confidence, inferred_reason = infer_concept_class(
            group[0]["observation_kind"],
            representative,
            group[0]["source_file"],
        )
        manual = manual_decisions.get(normalized_form)
        concept_class = manual.get("concept_class") if isinstance(manual, dict) else inferred_class
        canonical_name = manual.get("canonical_name") if isinstance(manual, dict) else representative
        status = manual.get("status") if isinstance(manual, dict) else ("approved" if inferred_confidence >= REVIEW_CONFIDENCE_THRESHOLD and inferred_class != "unclassified" else "review_required")
        concept = {
            "concept_id": normalized_form,
            "canonical_name": canonical_name,
            "concept_class": concept_class,
            "aliases": [alias for alias in observed_forms if alias != canonical_name],
            "observed_forms": observed_forms,
            "evidence": evidence,
            "status": status,
            "inference": {
                "confidence": inferred_confidence,
                "reason": inferred_reason,
                "source": "manual" if isinstance(manual, dict) else "auto",
            },
        }
        concepts.append(concept)
        if status != "approved":
            review_queue.append(concept)
    return concepts, review_queue


def export_vocabulary(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    max_observations: int | None = DEFAULT_MAX_OBSERVATIONS,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset_root = runtime_root / "minimal-dataset"
    file_parts = load_jsonl(dataset_root / "file-parts.jsonl")
    vocabulary_root = runtime_root / "vocabulary"
    observations_root = vocabulary_root / "observations"
    concepts_root = vocabulary_root / "concepts"
    review_root = vocabulary_root / "review"

    observations = extract_observations(file_parts=file_parts, max_observations=max_observations)
    concepts, review_queue = build_concepts(observations, runtime_root)

    write_json(observations_root / "observations.json", observations)
    write_json(concepts_root / "concepts.json", concepts)
    write_json(review_root / "review-queue.json", review_queue)

    class_counts = Counter(concept["concept_class"] for concept in concepts)
    summary = {
        "observation_count": len(observations),
        "concept_count": len(concepts),
        "review_queue_count": len(review_queue),
        "concept_class_counts": dict(sorted(class_counts.items())),
        "artifacts": {
            "observations": str(observations_root / "observations.json"),
            "concepts": str(concepts_root / "concepts.json"),
            "review_queue": str(review_root / "review-queue.json"),
            "manual_decisions": str(review_root / "manual-decisions.json"),
        },
        "provenance": provenance or {},
    }
    write_json(vocabulary_root / "summary.json", summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Concept-first vocabulary pipeline")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    parser.add_argument("--snapshot-id")
    parser.add_argument("--source-data-ref")
    parser.add_argument("--source-data-commit")
    parser.add_argument("--max-observations", type=int, default=DEFAULT_MAX_OBSERVATIONS)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    resolved_runtime_root = snapshot_runtime_root(args.runtime_root, args.snapshot_id)
    provenance = resolve_snapshot_provenance(
        snapshot_id=args.snapshot_id,
        source_data_ref=args.source_data_ref,
        source_data_commit=args.source_data_commit,
    )
    result = export_vocabulary(
        runtime_root=resolved_runtime_root,
        max_observations=args.max_observations,
        provenance=provenance,
    )
    result["runtime_root"] = str(resolved_runtime_root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
