from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from bespoke_cli.prototype_dataset import build_minimal_dataset
from bespoke_cli.snapshot_provenance import resolve_snapshot_provenance, snapshot_runtime_root

DEFAULT_MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DEFAULT_COMPARISON_MODELS = [
    "nomic-ai/nomic-embed-text-v1.5",
    "BAAI/bge-large-en-v1.5",
]
DEFAULT_RUNTIME_ROOT = Path("runtime/prototypes/repo-stripping")
DEFAULT_SEED_CONFIG = Path("discovery/config/seed-repos.json")
DEFAULT_MAX_CHARS = 1800
DEFAULT_OVERLAP = 200
DEFAULT_BATCH_SIZE = 16
DEFAULT_CLUSTER_THRESHOLD = 0.72
DEFAULT_MAX_UNITS = 1200
DEFAULT_NEIGHBORS = 5
DEFAULT_DEVICE = "auto"
MAX_CLUSTER_UNITS = 4000
MIN_CLUSTER_SIZE = 2
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "your",
    "you",
    "we",
    "our",
    "using",
    "use",
    "used",
    "via",
    "run",
    "runs",
    "file",
    "files",
    "repo",
    "repository",
    "project",
    "workflow",
    "workflows",
    "python",
    "json",
    "yaml",
    "yml",
    "github",
    "docs",
    "doc",
    "readme",
    "main",
    "name",
    "true",
    "false",
    "none",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: dict[str, Any] | list[dict[str, Any]] | list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def normalize_whitespace(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        window_end = min(len(text), start + max_chars)
        end = window_end
        if end < len(text):
            split = text.rfind("\n\n", start, end)
            if split <= start:
                split = text.rfind("\n", start, end)
            if split <= start:
                split = text.rfind(" ", start, end)
            minimum_acceptable_split = start + max_chars // 2
            if split >= minimum_acceptable_split:
                end = split
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = end - overlap
        start = max(next_start, start + max_chars // 2)
    return chunks


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    text = normalize_whitespace(text)
    if not text:
        return []
    header_pattern = re.compile(r"(?m)^(#{1,6}\s+.+)$")
    matches = list(header_pattern.finditer(text))
    if not matches:
        return [("document", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        intro = text[: matches[0].start()].strip()
        if intro:
            sections.append(("preamble", intro))
    for index, match in enumerate(matches):
        title = match.group(1).lstrip("#").strip()
        section_start = match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[section_start:section_end].strip()
        if section_text:
            sections.append((title, section_text))
    return sections


def split_by_line_pattern(text: str, pattern: str, title_cleaner=None) -> list[tuple[str, str]]:
    text = normalize_whitespace(text)
    if not text:
        return []
    regex = re.compile(pattern, re.MULTILINE)
    matches = list(regex.finditer(text))
    if not matches:
        return [("document", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append(("preamble", preamble))
    for index, match in enumerate(matches):
        title = match.group(0).strip()
        if title_cleaner is not None:
            title = title_cleaner(title)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((title, section_text))
    return sections


def split_structured_config(text: str, path: str) -> list[tuple[str, str]]:
    lower_path = path.lower()
    if lower_path.endswith(".toml"):
        return split_by_line_pattern(text, r"^\[[^\n\]]+\]\s*$")
    if lower_path.endswith((".yaml", ".yml")):
        return split_by_line_pattern(text, r"^(name|on|jobs|permissions|env|steps|services|volumes|body|inputs|outputs|with|run|uses|if|branches|paths):\s*(?:#.*)?$|^[A-Za-z0-9_.\-\"']+:\s*$")
    if lower_path.endswith(".json"):
        return split_by_line_pattern(text, r'^  "[^"]+":\s*(?:\{|\[|"|[0-9tfn-])')
    if lower_path.endswith("dockerfile") or Path(path).name.startswith("Dockerfile"):
        return split_by_line_pattern(text, r"^(FROM|RUN|COPY|ADD|ENV|ARG|WORKDIR|ENTRYPOINT|CMD|EXPOSE|LABEL)\b")
    return [("document", normalize_whitespace(text))]


def split_source_code(text: str, path: str) -> list[tuple[str, str]]:
    lower_path = path.lower()
    if lower_path.endswith(".py"):
        return split_by_line_pattern(text, r"^(async\s+def|def|class)\s+[A-Za-z_][A-Za-z0-9_]*")
    if lower_path.endswith((".js", ".jsx", ".ts", ".tsx")):
        return split_by_line_pattern(
            text,
            r"^(export\s+)?(async\s+)?function\s+[A-Za-z_][A-Za-z0-9_]*|^class\s+[A-Za-z_][A-Za-z0-9_]*|^(const|let|var)\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*(async\s*)?(\(|<)|^(export\s+default\s+function)\b",
        )
    if lower_path.endswith((".sh", ".bash")):
        return split_by_line_pattern(text, r"^(function\s+)?[A-Za-z_][A-Za-z0-9_]*\s*\(\)\s*\{")
    if lower_path.endswith((".go", ".java", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp")):
        return split_by_line_pattern(text, r"^(func|fn|class|struct|interface|enum|impl)\b")
    return [("document", normalize_whitespace(text))]


def derive_section_rows(part_kind: str, path: str, text: str) -> list[tuple[str, str]]:
    normalized = normalize_whitespace(text)
    if not normalized:
        return []
    lower_path = path.lower()
    if part_kind == "documentation":
        if lower_path.endswith(".md"):
            return split_markdown_sections(normalized)
        return split_by_line_pattern(normalized, r"^(#+\s+.+|[A-Z][A-Za-z0-9 /_-]{3,80}:)\s*$")
    if part_kind in {"manifest", "automation"}:
        return split_structured_config(normalized, path)
    if part_kind == "source":
        return split_source_code(normalized, path)
    return [("document", normalized)]


def build_embedding_units(
    file_parts: list[dict[str, Any]],
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for record in file_parts:
        repo_slug = record["repo_slug"]
        repo_name = record["repo_name"]
        commit = record["commit"]
        path = record["path"]
        part_kind = record["part_kind"]
        text = normalize_whitespace(record["text"])
        if not text:
            continue

        section_rows = derive_section_rows(part_kind=part_kind, path=path, text=text)

        for section_index, (section_title, section_text) in enumerate(section_rows):
            for chunk_index, chunk in enumerate(chunk_text(section_text, max_chars=max_chars, overlap=overlap)):
                unit_id = f"{repo_slug}:{path}:{section_index}:{chunk_index}"
                units.append(
                    {
                        "unit_id": unit_id,
                        "repo_name": repo_name,
                        "repo_slug": repo_slug,
                        "commit": commit,
                        "path": path,
                        "part_kind": part_kind,
                        "section_title": section_title,
                        "chunk_index": chunk_index,
                        "char_count": len(chunk),
                        "text": chunk,
                    }
                )
    return units


def downsample_units(units: list[dict[str, Any]], max_units: int | None) -> list[dict[str, Any]]:
    if max_units is None or len(units) <= max_units:
        return units

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for unit in units:
        key = (unit["part_kind"], unit["repo_slug"])
        buckets.setdefault(key, []).append(unit)

    ordered_keys = sorted(buckets)
    selected: list[dict[str, Any]] = []
    positions = {key: 0 for key in ordered_keys}
    while len(selected) < max_units:
        made_progress = False
        for key in ordered_keys:
            position = positions[key]
            bucket = buckets[key]
            if position >= len(bucket):
                continue
            selected.append(bucket[position])
            positions[key] += 1
            made_progress = True
            if len(selected) >= max_units:
                break
        if not made_progress:
            break
    return selected


def export_embedding_units(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
    max_units: int | None = DEFAULT_MAX_UNITS,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dataset_root = runtime_root / "minimal-dataset"
    file_parts_path = dataset_root / "file-parts.jsonl"
    units_root = runtime_root / "embedding-units"
    units_path = units_root / "units.jsonl"

    file_parts = load_jsonl(file_parts_path)
    units = build_embedding_units(file_parts=file_parts, max_chars=max_chars, overlap=overlap)
    units = downsample_units(units=units, max_units=max_units)
    write_jsonl(units_path, units)

    summary = {
        "source_file_parts": len(file_parts),
        "embedding_unit_count": len(units),
        "units_path": str(units_path),
        "counts_by_part_kind": dict(sorted(Counter(unit["part_kind"] for unit in units).items())),
        "max_chars": max_chars,
        "overlap": overlap,
        "max_units": max_units,
        "provenance": provenance or {},
    }
    write_json(units_root / "summary.json", summary)
    return summary


def model_supports_remote_code(model_name: str) -> bool:
    return model_name.startswith("nomic-ai/")


def model_task_prefix(model_name: str, task: str) -> str:
    if model_name.startswith("nomic-ai/"):
        if not task.endswith(":"):
            task = f"{task}:"
        return f"{task} "
    if model_name.startswith("BAAI/bge"):
        if task == "clustering":
            return "Represent this text for clustering: "
        if task == "classification":
            return "Represent this text for classification: "
    return ""


def probe_preferred_device(requested_device: str | None) -> dict[str, Any]:
    requested = requested_device or DEFAULT_DEVICE
    probe: dict[str, Any] = {
        "requested_device": requested,
        "selected_device": "cpu",
        "used_fallback": False,
        "fallback_reason": None,
        "cuda_visible": False,
        "cuda_device_name": None,
        "cuda_capability": None,
    }
    if requested == "cpu":
        return probe
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA requested explicitly but torch.cuda.is_available() is false")
        capability = torch.cuda.get_device_capability(0)
        probe.update(
            {
                "selected_device": "cuda",
                "cuda_visible": True,
                "cuda_device_name": torch.cuda.get_device_name(0),
                "cuda_capability": list(capability),
            }
        )
        return probe
    if requested == "auto" and torch.cuda.is_available():
        capability = torch.cuda.get_device_capability(0)
        probe.update(
            {
                "cuda_visible": True,
                "cuda_device_name": torch.cuda.get_device_name(0),
                "cuda_capability": list(capability),
            }
        )
        if tuple(capability) <= (12, 0):
            probe["selected_device"] = "cuda"
        else:
            probe["used_fallback"] = True
            probe["fallback_reason"] = (
                f"GPU capability {capability[0]}.{capability[1]} exceeds this torch build's advertised support; using CPU for reliability"
            )
    return probe


def load_model_and_tokenizer(model_name: str, device: str | None = None):
    trust_remote_code = model_supports_remote_code(model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=trust_remote_code)
    model = AutoModel.from_pretrained(model_name, trust_remote_code=trust_remote_code)
    device_probe = probe_preferred_device(device)
    resolved_device = device_probe["selected_device"]
    model.to(resolved_device)
    model.eval()
    return tokenizer, model, resolved_device, device_probe


def mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked = last_hidden_state * mask
    summed = masked.sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


@torch.inference_mode()
def embed_texts(
    texts: list[str],
    model_name: str = DEFAULT_MODEL_NAME,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    device: str | None = None,
) -> np.ndarray:
    embeddings, _device_probe = embed_texts_with_probe(
        texts=texts,
        model_name=model_name,
        task=task,
        batch_size=batch_size,
        device=device,
    )
    return embeddings


@torch.inference_mode()
def embed_texts_with_probe(
    texts: list[str],
    model_name: str = DEFAULT_MODEL_NAME,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    device: str | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    tokenizer, model, resolved_device, device_probe = load_model_and_tokenizer(model_name=model_name, device=device)
    prefix = model_task_prefix(model_name, task)
    all_vectors: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        if prefix:
            batch = [prefix + text for text in batch]
        tokenized = tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=min(getattr(tokenizer, "model_max_length", 512), 2048),
            return_tensors="pt",
        )
        tokenized = {key: value.to(resolved_device) for key, value in tokenized.items()}
        outputs = model(**tokenized)
        pooled = mean_pool(outputs.last_hidden_state, tokenized["attention_mask"])
        normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        all_vectors.append(normalized.cpu().numpy())
    if not all_vectors:
        return np.zeros((0, 0), dtype=np.float32), device_probe
    return np.vstack(all_vectors).astype(np.float32), device_probe


def sanitize_model_slug(model_name: str) -> str:
    return model_name.replace("/", "__")


def token_counts(texts: list[str], top_k: int = 8) -> list[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower()):
            if token in STOPWORDS:
                continue
            counts[token] += 1
    return [token for token, _ in counts.most_common(top_k)]


def path_signature_counts(paths: list[str], top_k: int = 5) -> list[str]:
    counts: Counter[str] = Counter()
    for path in paths:
        parts = Path(path).parts
        if len(parts) >= 2:
            counts[f"{parts[0]}/{parts[1]}"] += 1
        elif parts:
            counts[parts[0]] += 1
    return [value for value, _ in counts.most_common(top_k)]


def unit_sort_key(unit: dict[str, Any]) -> tuple[Any, ...]:
    return (
        unit["repo_slug"],
        unit["part_kind"],
        unit["path"],
        unit["section_title"],
        unit["chunk_index"],
    )


def summarize_unit_sample(unit: dict[str, Any]) -> dict[str, Any]:
    return {
        "unit_id": unit["unit_id"],
        "path": unit["path"],
        "part_kind": unit["part_kind"],
        "section_title": unit["section_title"],
        "text_preview": unit["text"][:220],
    }


def cluster_units_by_threshold(embeddings: np.ndarray, threshold: float) -> list[list[int]]:
    if len(embeddings) == 0:
        return []
    sims = embeddings @ embeddings.T
    visited = set()
    clusters: list[list[int]] = []
    for idx in range(len(embeddings)):
        if idx in visited:
            continue
        queue = [idx]
        visited.add(idx)
        cluster: list[int] = []
        while queue:
            current = queue.pop()
            cluster.append(current)
            neighbors = np.where(sims[current] >= threshold)[0]
            for neighbor in neighbors.tolist():
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        clusters.append(sorted(cluster))
    clusters.sort(key=len, reverse=True)
    return clusters


def agglomerative_clusters(embeddings: np.ndarray, threshold: float) -> list[list[int]]:
    if len(embeddings) == 0:
        return []
    similarity = embeddings @ embeddings.T
    clusters: list[list[int]] = [[index] for index in range(len(embeddings))]
    while True:
        best_pair: tuple[int, int] | None = None
        best_score = -1.0
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                values = [similarity[i, j] for i in clusters[left] for j in clusters[right]]
                score = float(sum(values) / len(values))
                if score > best_score:
                    best_score = score
                    best_pair = (left, right)
        if best_pair is None or best_score < threshold:
            break
        left, right = best_pair
        merged = sorted(clusters[left] + clusters[right])
        clusters = [cluster for index, cluster in enumerate(clusters) if index not in {left, right}]
        clusters.append(merged)
    clusters.sort(key=len, reverse=True)
    return clusters


def adaptive_cluster_assignments(
    units: list[dict[str, Any]],
    embeddings: np.ndarray,
    threshold: float = DEFAULT_CLUSTER_THRESHOLD,
) -> tuple[list[list[int]], dict[str, Any]]:
    if len(units) == 0:
        return [], {"strategy": "empty", "requested_threshold": threshold, "used_thresholds": {}}

    part_kind_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, unit in enumerate(units):
        part_kind_to_indexes[unit["part_kind"]].append(index)

    all_clusters: list[list[int]] = []
    used_thresholds: dict[str, float] = {}
    for part_kind, indexes in sorted(part_kind_to_indexes.items()):
        part_embeddings = embeddings[indexes]
        local_threshold = threshold
        clusters = agglomerative_clusters(part_embeddings, local_threshold)
        while len(indexes) >= MIN_CLUSTER_SIZE and len(clusters) <= 1 and local_threshold < 0.9:
            local_threshold = round(local_threshold + 0.04, 2)
            clusters = agglomerative_clusters(part_embeddings, local_threshold)
        used_thresholds[part_kind] = local_threshold
        for cluster in clusters:
            mapped = [indexes[local_index] for local_index in cluster]
            all_clusters.append(sorted(mapped))

    all_clusters.sort(key=len, reverse=True)
    return all_clusters, {
        "strategy": "per-part-kind-agglomerative-average-linkage",
        "requested_threshold": threshold,
        "used_thresholds": used_thresholds,
    }


def intra_cluster_similarity(member_indexes: list[int], similarity_matrix: np.ndarray) -> float:
    if len(member_indexes) <= 1:
        return 1.0
    values = []
    for left_pos, left in enumerate(member_indexes):
        for right in member_indexes[left_pos + 1 :]:
            values.append(float(similarity_matrix[left, right]))
    return round(sum(values) / len(values), 4) if values else 1.0


def summarize_clusters(units: list[dict[str, Any]], embeddings: np.ndarray, clusters: list[list[int]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    similarity_matrix = embeddings @ embeddings.T if len(embeddings) else np.zeros((0, 0), dtype=np.float32)
    for cluster_index, member_indexes in enumerate(clusters):
        member_units = [units[index] for index in member_indexes]
        member_units_sorted = sorted(member_units, key=unit_sort_key)
        part_kind_counts = Counter(unit["part_kind"] for unit in member_units_sorted)
        repo_counts = Counter(unit["repo_slug"] for unit in member_units_sorted)
        section_counts = Counter(unit["section_title"] for unit in member_units_sorted if unit["section_title"] != "document")
        path_prefix_counts = path_signature_counts([unit["path"] for unit in member_units_sorted], top_k=5)
        keywords = token_counts([unit["text"] for unit in member_units_sorted], top_k=8)
        exemplar = member_units_sorted[0]
        label_parts = keywords[:3] if keywords else path_prefix_counts[:2]
        summaries.append(
            {
                "cluster_id": cluster_index,
                "label": ", ".join(label_parts) if label_parts else exemplar["part_kind"],
                "size": len(member_units_sorted),
                "part_kind_counts": dict(sorted(part_kind_counts.items())),
                "repo_counts": dict(sorted(repo_counts.items())),
                "top_section_titles": [title for title, _ in section_counts.most_common(5)],
                "top_path_prefixes": path_prefix_counts,
                "keywords": keywords,
                "mean_intra_cluster_similarity": intra_cluster_similarity(member_indexes, similarity_matrix),
                "exemplar": summarize_unit_sample(exemplar),
                "sample_members": [summarize_unit_sample(unit) for unit in member_units_sorted[:5]],
                "member_unit_ids": [unit["unit_id"] for unit in member_units_sorted],
            }
        )
    return summaries


def build_nearest_neighbors(
    units: list[dict[str, Any]],
    embeddings: np.ndarray,
    k: int = DEFAULT_NEIGHBORS,
) -> list[dict[str, Any]]:
    if len(units) == 0:
        return []
    sims = embeddings @ embeddings.T
    neighbors: list[dict[str, Any]] = []
    for index, unit in enumerate(units):
        scores = sims[index].copy()
        scores[index] = -1.0
        top_indexes = np.argsort(scores)[::-1][:k]
        neighbors.append(
            {
                "unit_id": unit["unit_id"],
                "path": unit["path"],
                "part_kind": unit["part_kind"],
                "neighbors": [
                    {
                        "unit_id": units[neighbor_index]["unit_id"],
                        "path": units[neighbor_index]["path"],
                        "part_kind": units[neighbor_index]["part_kind"],
                        "score": round(float(scores[neighbor_index]), 4),
                        "text_preview": units[neighbor_index]["text"][:160],
                    }
                    for neighbor_index in top_indexes.tolist()
                    if scores[neighbor_index] >= 0
                ],
            }
        )
    return neighbors


def cluster_signature(cluster: dict[str, Any]) -> str:
    part_kind = ",".join(sorted(cluster.get("part_kind_counts", {}).keys()))
    prefixes = "|".join(cluster.get("top_path_prefixes", [])[:3])
    keywords = "|".join(cluster.get("keywords", [])[:5])
    return f"{part_kind}::{prefixes}::{keywords}"


def infer_cluster_family(cluster: dict[str, Any]) -> dict[str, Any]:
    prefixes = set(cluster.get("top_path_prefixes", []))
    keywords = set(cluster.get("keywords", []))
    part_kinds = set(cluster.get("part_kind_counts", {}).keys())
    section_titles = set(cluster.get("top_section_titles", []))

    if any(prefix.startswith(".github/workflows") for prefix in prefixes):
        return {"family": "automation-workflows", "confidence": 0.95, "reason": "workflow prefixes"}
    if any(prefix.startswith(".github/ISSUE_TEMPLATE") for prefix in prefixes):
        return {"family": "governance-issue-templates", "confidence": 0.95, "reason": "issue template prefixes"}
    if any(prefix.startswith(".github/PULL_REQUEST_TEMPLATE") for prefix in prefixes):
        return {"family": "governance-pr-template", "confidence": 0.95, "reason": "pr template prefix"}
    if "Dockerfile" in prefixes or {"docker", "ghcr", "trixie"} & keywords:
        return {"family": "runtime-packaging", "confidence": 0.9, "reason": "docker/runtime indicators"}
    if {"pyproject.toml", "package.json", "requirements.txt"} & prefixes:
        return {"family": "project-manifests", "confidence": 0.85, "reason": "manifest prefixes"}
    if {"description", "attributes", "labels", "issue"} & keywords:
        return {"family": "metadata-schemas", "confidence": 0.8, "reason": "schema keywords"}
    if {"change", "changes", "fix", "issue", "test"} & keywords or {"Changes Made", "How to Test", "Related Issue"} & section_titles:
        return {"family": "change-management-docs", "confidence": 0.8, "reason": "change-management signals"}
    if {"install", "usage", "guide", "docs"} & keywords:
        return {"family": "operator-docs", "confidence": 0.75, "reason": "operator-doc keywords"}
    if part_kinds == {"source"}:
        return {"family": "implementation-code", "confidence": 0.55, "reason": "source-only fallback"}
    if part_kinds == {"manifest"}:
        return {"family": "runtime-and-manifest", "confidence": 0.55, "reason": "manifest-only fallback"}
    if part_kinds == {"automation"}:
        return {"family": "automation-misc", "confidence": 0.45, "reason": "automation-only fallback"}
    if part_kinds == {"documentation"}:
        return {"family": "documentation-misc", "confidence": 0.45, "reason": "documentation-only fallback"}
    return {"family": "mixed-other", "confidence": 0.2, "reason": "no strong family signals"}


def load_manual_family_labels(runtime_root: Path) -> dict[str, Any]:
    labels_root = runtime_root / "embeddings" / "family-labeling"
    labels_root.mkdir(parents=True, exist_ok=True)
    labels_path = labels_root / "manual-labels.json"
    if not labels_path.exists():
        write_json(labels_path, {"labels": {}})
        return {"labels": {}}
    return load_json(labels_path)


def build_cluster_family_report(clusters: list[dict[str, Any]], runtime_root: Path) -> dict[str, Any]:
    manual_labels = load_manual_family_labels(runtime_root).get("labels", {})
    family_counts = Counter()
    family_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dead_letter_queue: list[dict[str, Any]] = []
    labeled_clusters: list[dict[str, Any]] = []
    for cluster in clusters:
        signature = cluster_signature(cluster)
        inferred = infer_cluster_family(cluster)
        manual = manual_labels.get(signature)
        family = manual.get("family") if isinstance(manual, dict) else inferred["family"]
        source = "manual" if isinstance(manual, dict) else "auto"
        confidence = 1.0 if source == "manual" else inferred["confidence"]
        review_required = source != "manual" and (confidence < 0.7 or family in {"automation-misc", "documentation-misc", "mixed-other"})
        cluster_record = {
            "cluster_id": cluster.get("cluster_id", 0),
            "signature": signature,
            "family": family,
            "source": source,
            "confidence": confidence,
            "reason": inferred["reason"],
            "label": cluster["label"],
            "size": cluster["size"],
            "top_path_prefixes": cluster.get("top_path_prefixes", [])[:3],
            "keywords": cluster.get("keywords", [])[:5],
            "review_required": review_required,
        }
        labeled_clusters.append(cluster_record)
        if review_required:
            dead_letter_queue.append(cluster_record)
        family_counts[family] += 1
        if len(family_examples[family]) < 3:
            family_examples[family].append(cluster_record)
    return {
        "family_counts": dict(sorted(family_counts.items())),
        "family_examples": dict(sorted(family_examples.items())),
        "dominant_families": [family for family, _ in family_counts.most_common(10)],
        "labeled_clusters": labeled_clusters,
        "dead_letter_queue": dead_letter_queue,
    }


def build_pattern_report(
    units: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    summary: dict[str, Any],
    runtime_root: Path,
) -> dict[str, Any]:
    counts_by_path_prefix = Counter()
    counts_by_section = Counter()
    for unit in units:
        counts_by_section[unit["section_title"]] += 1
        prefix_parts = Path(unit["path"]).parts
        if len(prefix_parts) >= 2:
            counts_by_path_prefix[f"{prefix_parts[0]}/{prefix_parts[1]}"] += 1
        elif prefix_parts:
            counts_by_path_prefix[prefix_parts[0]] += 1

    dominant_clusters = [cluster for cluster in clusters if cluster["size"] >= MIN_CLUSTER_SIZE]
    per_kind_clusters = Counter()
    for cluster in dominant_clusters:
        for part_kind, count in cluster["part_kind_counts"].items():
            if count == cluster["size"]:
                per_kind_clusters[part_kind] += 1
    family_report = build_cluster_family_report(clusters, runtime_root)

    return {
        "model_name": summary["model_name"],
        "embedding_count": summary["embedding_count"],
        "cluster_count": len(clusters),
        "dominant_cluster_count": len(dominant_clusters),
        "counts_by_part_kind": dict(sorted(Counter(unit["part_kind"] for unit in units).items())),
        "top_path_prefixes": [value for value, _ in counts_by_path_prefix.most_common(10)],
        "top_sections": [value for value, _ in counts_by_section.most_common(10)],
        "dominant_cluster_labels": [cluster["label"] for cluster in dominant_clusters[:10]],
        "dominant_cluster_sizes": [cluster["size"] for cluster in dominant_clusters[:10]],
        "pure_part_kind_cluster_counts": dict(sorted(per_kind_clusters.items())),
        "family_counts": family_report["family_counts"],
        "family_examples": family_report["family_examples"],
        "dominant_families": family_report["dominant_families"],
        "labeled_clusters": family_report["labeled_clusters"],
        "dead_letter_queue": family_report["dead_letter_queue"],
    }


def render_report_markdown(
    summary: dict[str, Any],
    pattern_report: dict[str, Any],
    clusters: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Single-repo embedding report: {summary['model_name']}",
        "",
        "## Corpus summary",
        f"- embedding_count: {summary['embedding_count']}",
        f"- embedding_dimension: {summary['embedding_dimension']}",
        f"- cluster_count: {summary['cluster_count']}",
        f"- cluster_strategy: {summary.get('cluster_strategy')}",
        f"- requested_threshold: {summary.get('cluster_threshold')}",
        f"- counts_by_part_kind: {pattern_report['counts_by_part_kind']}",
        f"- dominant_families: {pattern_report.get('dominant_families', [])}",
        "",
        "## Dominant patterns",
    ]
    for cluster in clusters[:10]:
        lines.extend(
            [
                f"### Cluster {cluster['cluster_id']}: {cluster['label']}",
                f"- size: {cluster['size']}",
                f"- part_kind_counts: {cluster['part_kind_counts']}",
                f"- top_path_prefixes: {cluster['top_path_prefixes']}",
                f"- keywords: {cluster['keywords']}",
                f"- top_section_titles: {cluster['top_section_titles']}",
                f"- mean_intra_cluster_similarity: {cluster['mean_intra_cluster_similarity']}",
                f"- exemplar: {cluster['exemplar']['path']} :: {cluster['exemplar']['text_preview']}",
                "",
            ]
        )
    lines.append("## Nearest-neighbor examples")
    for neighbor_row in neighbors[:10]:
        if not neighbor_row["neighbors"]:
            continue
        top_neighbor = neighbor_row["neighbors"][0]
        lines.extend(
            [
                f"- {neighbor_row['path']} -> {top_neighbor['path']} (score={top_neighbor['score']})",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def run_embedding_stage(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    model_name: str = DEFAULT_MODEL_NAME,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    device: str | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    units_root = runtime_root / "embedding-units"
    units_path = units_root / "units.jsonl"
    units = load_jsonl(units_path)
    texts = [unit["text"] for unit in units]
    embeddings, device_probe = embed_texts_with_probe(
        texts=texts,
        model_name=model_name,
        task=task,
        batch_size=batch_size,
        device=device,
    )

    output_root = runtime_root / "embeddings" / sanitize_model_slug(model_name)
    output_root.mkdir(parents=True, exist_ok=True)
    np.save(output_root / "vectors.npy", embeddings)
    write_jsonl(output_root / "units.jsonl", units)

    cluster_summaries: list[dict[str, Any]] = []
    cluster_metadata: dict[str, Any] = {"strategy": None, "requested_threshold": cluster_threshold, "used_thresholds": {}}
    if len(units) <= MAX_CLUSTER_UNITS:
        cluster_indexes, cluster_metadata = adaptive_cluster_assignments(units, embeddings, threshold=cluster_threshold)
        cluster_summaries = summarize_clusters(units, embeddings, cluster_indexes)
        write_json(output_root / "clusters.json", cluster_summaries)

    neighbors = build_nearest_neighbors(units, embeddings, k=DEFAULT_NEIGHBORS)
    write_json(output_root / "neighbors.json", neighbors)
    pattern_report = build_pattern_report(units, cluster_summaries, {
        "model_name": model_name,
        "embedding_count": int(embeddings.shape[0]),
    }, runtime_root=runtime_root)
    write_json(output_root / "pattern-report.json", pattern_report)
    family_labeling_root = runtime_root / "embeddings" / "family-labeling"
    write_json(family_labeling_root / f"{sanitize_model_slug(model_name)}-labeled-clusters.json", pattern_report["labeled_clusters"])
    write_json(family_labeling_root / f"{sanitize_model_slug(model_name)}-dead-letter-queue.json", pattern_report["dead_letter_queue"])

    summary = {
        "model_name": model_name,
        "task": task,
        "device": device_probe["selected_device"],
        "device_probe": device_probe,
        "embedding_count": int(embeddings.shape[0]),
        "embedding_dimension": int(embeddings.shape[1]) if embeddings.ndim == 2 and embeddings.size else 0,
        "batch_size": batch_size,
        "cluster_threshold": cluster_threshold,
        "cluster_count": len(cluster_summaries),
        "cluster_strategy": cluster_metadata["strategy"],
        "cluster_thresholds_by_part_kind": cluster_metadata["used_thresholds"],
        "artifacts": {
            "vectors": str(output_root / "vectors.npy"),
            "units": str(output_root / "units.jsonl"),
            "clusters": str(output_root / "clusters.json") if cluster_summaries else None,
            "neighbors": str(output_root / "neighbors.json"),
            "pattern_report": str(output_root / "pattern-report.json"),
        },
        "provenance": provenance or {},
    }
    write_json(output_root / "summary.json", summary)
    report_md = render_report_markdown(summary, pattern_report, cluster_summaries, neighbors)
    (output_root / "report.md").write_text(report_md)
    summary["artifacts"]["report_markdown"] = str(output_root / "report.md")
    write_json(output_root / "summary.json", summary)
    return summary


def pairwise_model_agreement(
    first_vectors: np.ndarray,
    second_vectors: np.ndarray,
    k: int = 3,
) -> float:
    if len(first_vectors) == 0 or len(second_vectors) == 0:
        return 0.0
    first_sims = first_vectors @ first_vectors.T
    second_sims = second_vectors @ second_vectors.T
    overlaps = []
    for index in range(len(first_vectors)):
        first_scores = first_sims[index].copy()
        second_scores = second_sims[index].copy()
        first_scores[index] = -1.0
        second_scores[index] = -1.0
        first_top = set(np.argsort(first_scores)[::-1][:k].tolist())
        second_top = set(np.argsort(second_scores)[::-1][:k].tolist())
        overlaps.append(len(first_top & second_top) / max(1, k))
    return round(sum(overlaps) / len(overlaps), 4)


def compare_models(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    models: list[str] | None = None,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    device: str | None = None,
) -> dict[str, Any]:
    model_names = models or list(DEFAULT_COMPARISON_MODELS)
    results = []
    vectors_by_model: dict[str, np.ndarray] = {}
    for model_name in model_names:
        summary = run_embedding_stage(
            runtime_root=runtime_root,
            model_name=model_name,
            task=task,
            batch_size=batch_size,
            cluster_threshold=cluster_threshold,
            device=device,
        )
        output_root = runtime_root / "embeddings" / sanitize_model_slug(model_name)
        pattern_report = load_json(output_root / "pattern-report.json")
        results.append(
            {
                "model_name": model_name,
                "embedding_dimension": summary["embedding_dimension"],
                "cluster_count": summary["cluster_count"],
                "cluster_strategy": summary["cluster_strategy"],
                "dominant_cluster_count": pattern_report["dominant_cluster_count"],
                "dominant_cluster_labels": pattern_report["dominant_cluster_labels"][:5],
                "top_path_prefixes": pattern_report["top_path_prefixes"][:5],
                "artifacts": summary["artifacts"],
            }
        )
        vectors_by_model[model_name] = np.load(output_root / "vectors.npy")

    agreement = {}
    for left_index, left_name in enumerate(model_names):
        for right_name in model_names[left_index + 1 :]:
            key = f"{sanitize_model_slug(left_name)}__vs__{sanitize_model_slug(right_name)}"
            agreement[key] = pairwise_model_agreement(vectors_by_model[left_name], vectors_by_model[right_name])

    comparison = {
        "models": results,
        "pairwise_neighbor_agreement_at_3": agreement,
    }
    write_json(runtime_root / "embeddings" / "model-comparison.json", comparison)
    return comparison


def cluster_membership_map(units: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> dict[str, int]:
    membership: dict[str, int] = {}
    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        for unit_id in cluster["member_unit_ids"]:
            membership[unit_id] = cluster_id
    return membership


def cluster_path_prefix_set(cluster: dict[str, Any]) -> set[str]:
    return set(cluster.get("top_path_prefixes", []))


def best_cluster_jaccard_summary(clusters_a: list[dict[str, Any]], clusters_b: list[dict[str, Any]]) -> dict[str, float]:
    if not clusters_a or not clusters_b:
        return {"average_best_jaccard": 0.0, "average_prefix_overlap": 0.0}
    jaccards = []
    prefix_overlaps = []
    member_sets_b = [set(cluster.get("member_unit_ids", [])) for cluster in clusters_b]
    prefix_sets_b = [cluster_path_prefix_set(cluster) for cluster in clusters_b]
    for cluster_a in clusters_a:
        members_a = set(cluster_a.get("member_unit_ids", []))
        prefixes_a = cluster_path_prefix_set(cluster_a)
        best_jaccard = 0.0
        best_prefix = 0.0
        for members_b, prefixes_b in zip(member_sets_b, prefix_sets_b):
            union = members_a | members_b
            member_jaccard = len(members_a & members_b) / len(union) if union else 1.0
            prefix_union = prefixes_a | prefixes_b
            prefix_jaccard = len(prefixes_a & prefixes_b) / len(prefix_union) if prefix_union else 1.0
            best_jaccard = max(best_jaccard, member_jaccard)
            best_prefix = max(best_prefix, prefix_jaccard)
        jaccards.append(best_jaccard)
        prefix_overlaps.append(best_prefix)
    return {
        "average_best_jaccard": round(sum(jaccards) / len(jaccards), 4),
        "average_prefix_overlap": round(sum(prefix_overlaps) / len(prefix_overlaps), 4),
    }


def pairwise_shared_neighbor_agreement(
    unit_ids_a: list[str],
    vectors_a: np.ndarray,
    unit_ids_b: list[str],
    vectors_b: np.ndarray,
    k: int = 3,
) -> float:
    shared_ids = [unit_id for unit_id in unit_ids_a if unit_id in set(unit_ids_b)]
    if len(shared_ids) <= 1:
        return 0.0
    index_a = {unit_id: idx for idx, unit_id in enumerate(unit_ids_a)}
    index_b = {unit_id: idx for idx, unit_id in enumerate(unit_ids_b)}
    shared_index_a = [index_a[unit_id] for unit_id in shared_ids]
    shared_index_b = [index_b[unit_id] for unit_id in shared_ids]
    sub_a = vectors_a[shared_index_a]
    sub_b = vectors_b[shared_index_b]
    return pairwise_model_agreement(sub_a, sub_b, k=k)


def cluster_membership_agreement(units_a: list[dict[str, Any]], clusters_a: list[dict[str, Any]], units_b: list[dict[str, Any]], clusters_b: list[dict[str, Any]]) -> float:
    map_a = cluster_membership_map(units_a, clusters_a)
    map_b = cluster_membership_map(units_b, clusters_b)
    shared_ids = [unit_id for unit_id in map_a if unit_id in map_b]
    if not shared_ids:
        return 0.0
    matches = sum(1 for unit_id in shared_ids if map_a[unit_id] == map_b[unit_id])
    return round(matches / len(shared_ids), 4)


def dominant_cluster_label_overlap(clusters_a: list[dict[str, Any]], clusters_b: list[dict[str, Any]], top_n: int = 5) -> float:
    labels_a = {cluster["label"] for cluster in clusters_a[:top_n]}
    labels_b = {cluster["label"] for cluster in clusters_b[:top_n]}
    if not labels_a and not labels_b:
        return 1.0
    union = labels_a | labels_b
    if not union:
        return 0.0
    return round(len(labels_a & labels_b) / len(union), 4)


def evaluate_stability(
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    models: list[str] | None = None,
    sample_sizes: list[int] | None = None,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    device: str | None = None,
) -> dict[str, Any]:
    model_names = models or list(DEFAULT_COMPARISON_MODELS)
    requested_sample_sizes = sample_sizes or [32, 64, 128]

    dataset_root = runtime_root / "minimal-dataset"
    file_parts = load_jsonl(dataset_root / "file-parts.jsonl")
    full_units = build_embedding_units(file_parts=file_parts, max_chars=DEFAULT_MAX_CHARS, overlap=DEFAULT_OVERLAP)
    usable_sizes = sorted({size for size in requested_sample_sizes if size > 0 and size <= len(full_units)})

    runs: list[dict[str, Any]] = []
    by_key: dict[tuple[str, int], dict[str, Any]] = {}
    for sample_size in usable_sizes:
        units = downsample_units(full_units, sample_size)
        unit_ids = [unit["unit_id"] for unit in units]
        texts = [unit["text"] for unit in units]
        for model_name in model_names:
            embeddings, device_probe = embed_texts_with_probe(
                texts=texts,
                model_name=model_name,
                task=task,
                batch_size=batch_size,
                device=device,
            )
            cluster_indexes, cluster_metadata = adaptive_cluster_assignments(units, embeddings, threshold=cluster_threshold)
            clusters = summarize_clusters(units, embeddings, cluster_indexes)
            pattern_report = build_pattern_report(
                units,
                clusters,
                {"model_name": model_name, "embedding_count": len(units)},
                runtime_root=runtime_root,
            )
            run = {
                "model_name": model_name,
                "sample_size": sample_size,
                "device": device_probe["selected_device"],
                "device_probe": device_probe,
                "cluster_count": len(clusters),
                "cluster_strategy": cluster_metadata["strategy"],
                "cluster_thresholds_by_part_kind": cluster_metadata["used_thresholds"],
                "dominant_cluster_labels": pattern_report["dominant_cluster_labels"][:5],
                "dominant_families": pattern_report["dominant_families"][:5],
                "top_path_prefixes": pattern_report["top_path_prefixes"][:5],
            }
            runs.append(run)
            by_key[(model_name, sample_size)] = {
                "unit_ids": unit_ids,
                "vectors": embeddings,
                "clusters": clusters,
                "units": units,
            }

    within_model_stability = []
    for model_name in model_names:
        for left_index, sample_size_a in enumerate(usable_sizes):
            for sample_size_b in usable_sizes[left_index + 1 :]:
                first = by_key[(model_name, sample_size_a)]
                second = by_key[(model_name, sample_size_b)]
                within_model_stability.append(
                    {
                        "model_name": model_name,
                        "sample_size_a": sample_size_a,
                        "sample_size_b": sample_size_b,
                        "shared_neighbor_agreement_at_3": pairwise_shared_neighbor_agreement(
                            first["unit_ids"],
                            first["vectors"],
                            second["unit_ids"],
                            second["vectors"],
                            k=3,
                        ),
                        "cluster_membership_agreement": cluster_membership_agreement(
                            first["units"],
                            first["clusters"],
                            second["units"],
                            second["clusters"],
                        ),
                        "cluster_best_match": best_cluster_jaccard_summary(first["clusters"], second["clusters"]),
                        "dominant_cluster_label_overlap": dominant_cluster_label_overlap(first["clusters"], second["clusters"]),
                    }
                )

    cross_model_stability = []
    for sample_size in usable_sizes:
        for left_index, model_name_a in enumerate(model_names):
            for model_name_b in model_names[left_index + 1 :]:
                first = by_key[(model_name_a, sample_size)]
                second = by_key[(model_name_b, sample_size)]
                cross_model_stability.append(
                    {
                        "sample_size": sample_size,
                        "model_a": model_name_a,
                        "model_b": model_name_b,
                        "shared_neighbor_agreement_at_3": pairwise_shared_neighbor_agreement(
                            first["unit_ids"],
                            first["vectors"],
                            second["unit_ids"],
                            second["vectors"],
                            k=3,
                        ),
                        "cluster_best_match": best_cluster_jaccard_summary(first["clusters"], second["clusters"]),
                        "dominant_cluster_label_overlap": dominant_cluster_label_overlap(first["clusters"], second["clusters"]),
                    }
                )

    summary = {
        "sample_sizes": usable_sizes,
        "models": model_names,
        "runs": runs,
        "within_model_stability": within_model_stability,
        "cross_model_stability": cross_model_stability,
    }
    write_json(runtime_root / "embeddings" / "stability-evaluation.json", summary)
    return summary


def generate_report(runtime_root: Path = DEFAULT_RUNTIME_ROOT, model_name: str = DEFAULT_MODEL_NAME) -> dict[str, Any]:
    output_root = runtime_root / "embeddings" / sanitize_model_slug(model_name)
    summary = load_json(output_root / "summary.json")
    pattern_report = load_json(output_root / "pattern-report.json")
    clusters = load_json(output_root / "clusters.json") if summary["artifacts"].get("clusters") else []
    neighbors = load_json(output_root / "neighbors.json")
    markdown = render_report_markdown(summary, pattern_report, clusters, neighbors)
    report_path = output_root / "report.md"
    report_path.write_text(markdown)
    return {
        "model_name": model_name,
        "report_path": str(report_path),
        "cluster_count": len(clusters),
        "neighbor_rows": len(neighbors),
        "dominant_cluster_labels": pattern_report["dominant_cluster_labels"][:10],
    }


def run_all(
    seed_config_path: Path = DEFAULT_SEED_CONFIG,
    runtime_root: Path = DEFAULT_RUNTIME_ROOT,
    limit: int | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    task: str = "clustering",
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
    max_units: int | None = DEFAULT_MAX_UNITS,
    cluster_threshold: float = DEFAULT_CLUSTER_THRESHOLD,
    device: str | None = None,
    snapshot_id: str | None = None,
    source_data_ref: str | None = None,
    source_data_commit: str | None = None,
) -> dict[str, Any]:
    resolved_runtime_root = snapshot_runtime_root(runtime_root, snapshot_id)
    provenance = resolve_snapshot_provenance(
        snapshot_id=snapshot_id,
        source_data_ref=source_data_ref,
        source_data_commit=source_data_commit,
    )
    dataset_summary = build_minimal_dataset(seed_config_path=seed_config_path, runtime_root=resolved_runtime_root, limit=limit)
    units_summary = export_embedding_units(
        runtime_root=resolved_runtime_root,
        max_chars=max_chars,
        overlap=overlap,
        max_units=max_units,
        provenance=provenance,
    )
    embedding_summary = run_embedding_stage(
        runtime_root=resolved_runtime_root,
        model_name=model_name,
        task=task,
        batch_size=batch_size,
        cluster_threshold=cluster_threshold,
        device=device,
        provenance=provenance,
    )
    combined = {
        "dataset": dataset_summary,
        "embedding_units": units_summary,
        "embeddings": embedding_summary,
        "provenance": provenance,
        "runtime_root": str(resolved_runtime_root),
    }
    write_json(resolved_runtime_root / "pipeline-summary.json", combined)
    return combined


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local GitHub-text embedding pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT)
    common.add_argument("--snapshot-id")
    common.add_argument("--source-data-ref")
    common.add_argument("--source-data-commit")

    run_all_parser = subparsers.add_parser("run-all", parents=[common])
    run_all_parser.add_argument("--seed-config", type=Path, default=DEFAULT_SEED_CONFIG)
    run_all_parser.add_argument("--limit", type=int)
    run_all_parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    run_all_parser.add_argument("--task", default="clustering")
    run_all_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    run_all_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    run_all_parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    run_all_parser.add_argument("--max-units", type=int, default=DEFAULT_MAX_UNITS)
    run_all_parser.add_argument("--cluster-threshold", type=float, default=DEFAULT_CLUSTER_THRESHOLD)
    run_all_parser.add_argument("--device", default=DEFAULT_DEVICE)

    export_parser = subparsers.add_parser("export-units", parents=[common])
    export_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    export_parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    export_parser.add_argument("--max-units", type=int, default=DEFAULT_MAX_UNITS)

    embed_parser = subparsers.add_parser("embed", parents=[common])
    embed_parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    embed_parser.add_argument("--task", default="clustering")
    embed_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    embed_parser.add_argument("--cluster-threshold", type=float, default=DEFAULT_CLUSTER_THRESHOLD)
    embed_parser.add_argument("--device", default=DEFAULT_DEVICE)

    compare_parser = subparsers.add_parser("compare-models", parents=[common])
    compare_parser.add_argument("--models", nargs="+", default=DEFAULT_COMPARISON_MODELS)
    compare_parser.add_argument("--task", default="clustering")
    compare_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    compare_parser.add_argument("--cluster-threshold", type=float, default=DEFAULT_CLUSTER_THRESHOLD)
    compare_parser.add_argument("--device", default=DEFAULT_DEVICE)

    stability_parser = subparsers.add_parser("evaluate-stability", parents=[common])
    stability_parser.add_argument("--models", nargs="+", default=DEFAULT_COMPARISON_MODELS)
    stability_parser.add_argument("--sample-sizes", nargs="+", type=int, default=[32, 64, 128])
    stability_parser.add_argument("--task", default="clustering")
    stability_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    stability_parser.add_argument("--cluster-threshold", type=float, default=DEFAULT_CLUSTER_THRESHOLD)
    stability_parser.add_argument("--device", default=DEFAULT_DEVICE)

    report_parser = subparsers.add_parser("report", parents=[common])
    report_parser.add_argument("--model", default=DEFAULT_MODEL_NAME)

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    resolved_runtime_root = snapshot_runtime_root(args.runtime_root, getattr(args, "snapshot_id", None))
    provenance = resolve_snapshot_provenance(
        snapshot_id=getattr(args, "snapshot_id", None),
        source_data_ref=getattr(args, "source_data_ref", None),
        source_data_commit=getattr(args, "source_data_commit", None),
    )

    if args.command == "run-all":
        result = run_all(
            seed_config_path=args.seed_config,
            runtime_root=args.runtime_root,
            limit=args.limit,
            model_name=args.model,
            task=args.task,
            batch_size=args.batch_size,
            max_chars=args.max_chars,
            overlap=args.overlap,
            max_units=args.max_units,
            cluster_threshold=args.cluster_threshold,
            device=args.device,
            snapshot_id=args.snapshot_id,
            source_data_ref=args.source_data_ref,
            source_data_commit=args.source_data_commit,
        )
    elif args.command == "export-units":
        result = export_embedding_units(
            runtime_root=resolved_runtime_root,
            max_chars=args.max_chars,
            overlap=args.overlap,
            max_units=args.max_units,
            provenance=provenance,
        )
    elif args.command == "embed":
        result = run_embedding_stage(
            runtime_root=resolved_runtime_root,
            model_name=args.model,
            task=args.task,
            batch_size=args.batch_size,
            cluster_threshold=args.cluster_threshold,
            device=args.device,
            provenance=provenance,
        )
    elif args.command == "compare-models":
        result = compare_models(
            runtime_root=resolved_runtime_root,
            models=args.models,
            task=args.task,
            batch_size=args.batch_size,
            cluster_threshold=args.cluster_threshold,
            device=args.device,
        )
        result["provenance"] = provenance
        result["runtime_root"] = str(resolved_runtime_root)
    elif args.command == "evaluate-stability":
        result = evaluate_stability(
            runtime_root=resolved_runtime_root,
            models=args.models,
            sample_sizes=args.sample_sizes,
            task=args.task,
            batch_size=args.batch_size,
            cluster_threshold=args.cluster_threshold,
            device=args.device,
        )
        result["provenance"] = provenance
        result["runtime_root"] = str(resolved_runtime_root)
    elif args.command == "report":
        result = generate_report(runtime_root=resolved_runtime_root, model_name=args.model)
        result["provenance"] = provenance
        result["runtime_root"] = str(resolved_runtime_root)
    else:
        raise ValueError(f"unknown command: {args.command}")

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
