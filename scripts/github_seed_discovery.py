#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import time
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = "https://api.github.com"
UA = "bespoke-cli-discovery"
REPO_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)")
MANIFEST_CANDIDATES = ["pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod", "Dockerfile"]
README_CANDIDATES = ["README.md", "README.rst", "README.txt"]
TOPIC_SKIP = {
    "ai",
    "agent",
    "agents",
    "ai-agent",
    "ai-agents",
    "claude",
    "codex",
    "copilot",
    "gpt",
    "llm",
    "openai",
    "python",
    "javascript",
    "typescript",
}
TOPIC_RESULT_LIMIT = 5
TOPIC_OWNER_CAP_PER_SOURCE = 1
NON_REPO_OWNERS = {"user-attachments", "orgs", "users", "settings", "marketplace", "sponsors"}
EXPLICIT_REPO_EXISTS_CACHE = {}
DEFAULT_DISCOVERY_BUDGET_SECONDS = 360
DEFAULT_DISCOVERY_MIN_REPO_START_SECONDS = 15
DEFAULT_DISCOVERY_HARD_STOP_SECONDS = 20
SLOW_REPO_THRESHOLD_SECONDS = 10.0


def api_get_json(url):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def github_repo(owner_repo):
    return api_get_json(f"{API_ROOT}/repos/{owner_repo}")


def is_valid_repo_full_name(text):
    parts = text.split('/')
    return len(parts) == 2 and all(parts)


def github_contents(owner_repo, path=""):
    encoded = urllib.parse.quote(path)
    return api_get_json(f"{API_ROOT}/repos/{owner_repo}/contents/{encoded}")


def github_search_repos(query, per_page):
    q = urllib.parse.quote(query)
    return api_get_json(f"{API_ROOT}/search/repositories?q={q}&sort=updated&order=desc&per_page={per_page}")


def decode_content(item):
    if item.get("encoding") == "base64":
        return base64.b64decode(item["content"]).decode("utf-8", "replace")
    return item.get("content", "")


def slug(text):
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-")


def normalize_term(text):
    text = re.sub(r"\s+", " ", text.strip()).strip("`'\" ")
    if len(text) < 3 or len(text) > 80:
        return None
    if text.count(" ") > 5:
        return None
    lowered = text.lower()
    if lowered.startswith(("for example", "example:", "e.g.", "i.e.")):
        return None
    if text.startswith("###") or text.startswith("##") or text.startswith("#"):
        return None
    if text[0].isdigit():
        return None
    if re.fullmatch(r"[-=:_./\\|]+", text):
        return None
    if re.search(r"[{}\[\]<>]", text):
        return None
    if text.startswith((".", "-", "_", ")", "(", "|", "*")):
        return None
    if "_" in text:
        return None
    if "/" in text or "\\" in text:
        return None
    if "|" in text:
        return None
    if "*." in text or text.endswith((".json", ".yaml", ".yml", ".py", ".sh", ".md", ".txt")):
        return None
    if re.fullmatch(r"[0-9.]+", text):
        return None
    if re.search(r"\b(json|yaml|yml|python|bash|shell|markdown)\b", lowered):
        return None
    if re.search(r"\b\d+(?:\.\d+){1,}\b", text):
        return None
    punct = len(re.findall(r"[^A-Za-z0-9\s-]", text))
    alnum = len(re.findall(r"[A-Za-z0-9]", text))
    if alnum == 0 or punct > max(2, alnum // 2):
        return None
    return text


def normalize_component(text):
    text = re.sub(r"\s+", "", text.strip()).strip("`'\"")
    if len(text) < 2 or len(text) > 120:
        return None
    if re.fullmatch(r"[-=:_./\\]+", text):
        return None
    if text.startswith((".", "-", "_")):
        return None
    return text


def canonicalize_repo_full_name(text, lowercase=False):
    text = text.strip().strip('/')
    if text.endswith('.git'):
        text = text[:-4]
    parts = text.split('/')
    if len(parts) != 2:
        return None
    owner, repo = parts
    if not owner or not repo:
        return None
    if lowercase:
        owner = owner.lower()
        repo = repo.lower()
    return f"{owner}/{repo}"


def repo_identity_key(text):
    canonical = canonicalize_repo_full_name(text, lowercase=True)
    if not canonical:
        return None
    return canonical


def is_plausible_repo_candidate(full_name):
    canonical = repo_identity_key(full_name)
    if not canonical:
        return False
    owner, repo = canonical.split('/')
    if owner in NON_REPO_OWNERS:
        return False
    if repo in {"assets", "releases", "issues", "pulls", "wiki", "blob", "tree"}:
        return False
    return True


def explicit_repo_exists(full_name):
    canonical = repo_identity_key(full_name)
    if not canonical or not is_plausible_repo_candidate(canonical):
        return False
    cached = EXPLICIT_REPO_EXISTS_CACHE.get(canonical)
    if cached is not None:
        return cached
    try:
        repo = github_repo(canonical)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            EXPLICIT_REPO_EXISTS_CACHE[canonical] = False
            return False
        raise
    result = bool(repo_identity_key(repo.get("full_name", canonical)))
    EXPLICIT_REPO_EXISTS_CACHE[canonical] = result
    return result


def normalize_topic(topic):
    return re.sub(r"\s+", "-", topic.strip().lower())


def is_specific_topic(topic):
    normalized = normalize_topic(topic)
    if not normalized:
        return False
    if normalized in TOPIC_SKIP:
        return False
    if len(normalized) < 4 or len(normalized) > 64:
        return False
    if re.fullmatch(r"[a-z]{1,3}", normalized):
        return False
    if re.fullmatch(r"[0-9._-]+", normalized):
        return False
    return True


def comparable_topic_set(topics):
    return {normalize_topic(topic) for topic in topics if is_specific_topic(topic)}


def merge_frontier_entries(existing, candidate):
    merged = dict(existing)
    for key in ("html_url", "description", "updated_at"):
        if not merged.get(key) and candidate.get(key):
            merged[key] = candidate[key]
    if not merged.get("topics") and candidate.get("topics"):
        merged["topics"] = candidate["topics"]
    merged["graph_distance"] = min(existing.get("graph_distance", 999999), candidate.get("graph_distance", 999999))

    existing_via = existing.get("discovered_via", "")
    candidate_via = candidate.get("discovered_via", "")
    if existing_via.startswith("topic:") and candidate_via and not candidate_via.startswith("topic:"):
        merged["discovered_via"] = candidate_via
    else:
        merged["discovered_via"] = existing_via or candidate_via
    return merged


def dedupe_frontier_entries(entries):
    deduped = {}
    ordered_keys = []
    for entry in entries:
        discovered_via = entry.get("discovered_via", "")
        if discovered_via.startswith("topic:"):
            topic = discovered_via.split(":", 1)[1]
            if not is_specific_topic(topic):
                continue
        canonical = canonicalize_repo_full_name(entry.get("full_name", ""), lowercase=True)
        if not canonical:
            continue
        if discovered_via == "explicit-github-link" and not is_plausible_repo_candidate(canonical):
            continue
        normalized_entry = dict(entry)
        normalized_entry["full_name"] = canonical
        if canonical in deduped:
            deduped[canonical] = merge_frontier_entries(deduped[canonical], normalized_entry)
        else:
            deduped[canonical] = normalized_entry
            ordered_keys.append(canonical)
    return [deduped[key] for key in ordered_keys]


def repo_link_priority(path):
    if path in README_CANDIDATES:
        return 0
    if path in MANIFEST_CANDIDATES:
        return 1
    return None


def limit_repo_links(repo_link_hits, edge_records, max_repo_links_per_repo):
    eligible = []
    for hit in repo_link_hits:
        priority = repo_link_priority(hit.get("source_file", ""))
        if priority is None:
            continue
        eligible.append((priority, hit))
    ordered = [
        hit for _, hit in sorted(
            eligible,
            key=lambda item: (
                item[0],
                item[1].get("source_file", ""),
                item[1].get("full_name", ""),
            ),
        )
    ]
    kept = ordered[:max_repo_links_per_repo]
    kept_keys = {
        (hit.get("full_name"), hit.get("source_file"), hit.get("edge_type"))
        for hit in kept
    }
    filtered_edges = []
    for edge in edge_records:
        if edge.get("target_type") != "repository" or edge.get("edge_type") != "explicit-github-link":
            filtered_edges.append(edge)
            continue
        key = (edge.get("target"), edge.get("source_file"), edge.get("edge_type"))
        if key in kept_keys:
            filtered_edges.append(edge)
    return kept, filtered_edges


def build_processed_history(frontier_state, processed_names):
    processed_history = []
    seen_processed = set()
    for full_name in frontier_state.get("processed", []) + processed_names:
        canonical = repo_identity_key(full_name)
        if not canonical or canonical in seen_processed:
            continue
        seen_processed.add(canonical)
        processed_history.append(canonical)
    return processed_history, seen_processed


def summarize_repo_timings(repo_timings):
    if not repo_timings:
        return {
            "count": 0,
            "total_seconds": 0.0,
            "average_seconds": 0.0,
            "max_seconds": 0.0,
        }
    durations = [item["elapsed_seconds"] for item in repo_timings]
    total = sum(durations)
    return {
        "count": len(repo_timings),
        "total_seconds": round(total, 3),
        "average_seconds": round(total / len(repo_timings), 3),
        "max_seconds": round(max(durations), 3),
    }


def unique_preserve(items):
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def concept_buckets_for_term(hit):
    edge_type = hit.get("edge_type")
    buckets = []
    if edge_type == "repo-topic":
        buckets.extend(["tool-component", "capability"])
    elif edge_type == "workflow-name":
        buckets.extend(["workflow-process", "data-document-artifact"])
    else:
        buckets.append("unclassified")
    return unique_preserve(buckets)


def concept_primary_bucket(hit):
    return concept_buckets_for_term(hit)[0]


def concept_id_for_term(term):
    return slug(term)


def observation_id_for_term(source_repo, source_file, edge_type, term):
    raw = f"{source_repo}|{source_file or ''}|{edge_type}|{term}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def upsert_concept_observation(observations_dir, generated_at, source_repo, hit):
    term = hit["term"]
    observation_id = observation_id_for_term(source_repo, hit.get("source_file"), hit.get("edge_type"), term)
    path = observations_dir / f"{observation_id}.json"
    buckets = concept_buckets_for_term(hit)
    payload = {
        "observation_id": observation_id,
        "concept_id": concept_id_for_term(term),
        "observed_text": term,
        "normalized_form": slug(term),
        "observation_kind": hit.get("edge_type"),
        "source_repo": source_repo,
        "source_file": hit.get("source_file"),
        "observed_at": generated_at,
        "candidate_buckets": buckets,
        "candidate_primary_bucket": buckets[0],
        "ambiguity_status": "unresolved",
        "candidate_senses": [
            {
                "sense_id": f"{concept_id_for_term(term)}#sense-1",
                "label": term,
                "status": "candidate",
                "candidate_buckets": buckets,
            }
        ],
    }
    write_json(path, payload)


def upsert_seeded_concept(concepts_dir, generated_at, concept_id, canonical_name, buckets, alias, evidence):
    path = concepts_dir / f"{concept_id}.json"
    buckets = unique_preserve(buckets)
    senses = [{
        "sense_id": f"{concept_id}#sense-1",
        "label": canonical_name,
        "status": "seeded-stable",
        "buckets": buckets,
    }]
    if path.exists():
        existing = json.loads(path.read_text())
        existing["last_seen_at"] = generated_at
        existing.setdefault("aliases", [])
        if alias not in existing["aliases"]:
            existing["aliases"].append(alias)
        existing.setdefault("buckets", [])
        existing["buckets"] = unique_preserve(existing["buckets"] + buckets)
        existing.setdefault("evidence", [])
        if evidence not in existing["evidence"]:
            existing["evidence"].append(evidence)
        existing["primary_bucket"] = existing.get("primary_bucket") or buckets[0]
        existing.setdefault("ambiguity_status", "seeded-stable")
        existing.setdefault("possible_senses", senses)
        write_json(path, existing)
        return
    payload = {
        "concept_id": concept_id,
        "canonical_name": canonical_name,
        "primary_bucket": buckets[0],
        "buckets": buckets,
        "aliases": [alias],
        "ambiguity_status": "seeded-stable",
        "possible_senses": senses,
        "first_seen_at": generated_at,
        "last_seen_at": generated_at,
        "evidence": [evidence],
    }
    write_json(path, payload)


def upsert_concept(concepts_dir, generated_at, source_repo, hit):
    term = hit["term"]
    concept_id = concept_id_for_term(term)
    path = concepts_dir / f"{concept_id}.json"
    buckets = concept_buckets_for_term(hit)
    alias = term
    evidence = {
        "source_repo": source_repo,
        "source_file": hit.get("source_file"),
        "discovered_via": hit.get("edge_type"),
        "observed_at": generated_at,
    }
    senses = [{
        "sense_id": f"{concept_id}#sense-1",
        "label": term,
        "status": "candidate",
        "buckets": buckets,
    }]
    if path.exists():
        existing = json.loads(path.read_text())
        existing["last_seen_at"] = generated_at
        existing.setdefault("aliases", [])
        if alias not in existing["aliases"]:
            existing["aliases"].append(alias)
        existing.setdefault("buckets", [])
        existing["buckets"] = unique_preserve(existing["buckets"] + buckets)
        existing.setdefault("evidence", [])
        if evidence not in existing["evidence"]:
            existing["evidence"].append(evidence)
        existing["primary_bucket"] = existing.get("primary_bucket") or buckets[0]
        existing.setdefault("ambiguity_status", "unresolved")
        existing.setdefault("possible_senses", senses)
        write_json(path, existing)
        return
    payload = {
        "concept_id": concept_id,
        "canonical_name": term,
        "primary_bucket": buckets[0],
        "buckets": buckets,
        "aliases": [alias],
        "ambiguity_status": "unresolved",
        "possible_senses": senses,
        "first_seen_at": generated_at,
        "last_seen_at": generated_at,
        "evidence": [evidence],
    }
    write_json(path, payload)


def upsert_seeded_language_concepts(concepts_dir, generated_at):
    seed_path = Path(__file__).resolve().parent.parent / "vocabulary" / "english" / "stable-closed-classes.json"
    repo_root = Path(__file__).resolve().parent.parent
    if not seed_path.exists():
        return
    seed = json.loads(seed_path.read_text())
    for category, entries in (seed.get("categories") or {}).items():
        for entry in entries:
            concept_id = f"en-{slug(category)}-{slug(entry)}"
            evidence = {
                "source_repo": "seed:english",
                "source_file": str(seed_path.relative_to(repo_root)),
                "discovered_via": "seeded-language-entity",
                "observed_at": generated_at,
            }
            upsert_seeded_concept(
                concepts_dir,
                generated_at,
                concept_id,
                entry,
                ["language-layer-entity", slug(category)],
                entry,
                evidence,
            )


def normalize_existing_concept_artifacts(concepts_dir):
    for path in concepts_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text())
        except Exception:
            path.unlink(missing_ok=True)
            continue
        buckets = obj.get("buckets") or []
        if not buckets:
            primary = obj.get("primary_bucket")
            if primary:
                buckets = [primary]
            else:
                evidence = obj.get("evidence") or []
                discovered_via = next((item.get("discovered_via") for item in evidence if item.get("discovered_via")), None)
                if discovered_via == "repo-topic":
                    buckets = ["tool-component", "capability"]
                elif discovered_via == "workflow-name":
                    buckets = ["workflow-process", "data-document-artifact"]
                elif discovered_via == "seeded-language-entity":
                    buckets = ["language-layer-entity"]
                else:
                    buckets = ["unclassified"]
        obj["buckets"] = unique_preserve(buckets)
        obj["primary_bucket"] = obj.get("primary_bucket") or obj["buckets"][0]
        obj.setdefault("aliases", [])
        if obj.get("canonical_name") and obj["canonical_name"] not in obj["aliases"]:
            obj["aliases"].append(obj["canonical_name"])
        discovered_via = next((item.get("discovered_via") for item in (obj.get("evidence") or []) if item.get("discovered_via")), None)
        default_status = "seeded-stable" if discovered_via == "seeded-language-entity" else "unresolved"
        obj.setdefault("ambiguity_status", default_status)
        if not obj.get("possible_senses"):
            obj["possible_senses"] = [{
                "sense_id": f"{obj.get('concept_id', slug(obj.get('canonical_name','concept')))}#sense-1",
                "label": obj.get("canonical_name") or obj.get("concept_id"),
                "status": "seeded-stable" if default_status == "seeded-stable" else "candidate",
                "buckets": obj["buckets"],
            }]
        write_json(path, obj)


def normalize_existing_concept_observations(observations_dir):
    for path in observations_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text())
        except Exception:
            path.unlink(missing_ok=True)
            continue
        candidate_buckets = obj.get("candidate_buckets") or []
        if not candidate_buckets:
            kind = obj.get("observation_kind")
            if kind == "repo-topic":
                candidate_buckets = ["tool-component", "capability"]
            elif kind == "workflow-name":
                candidate_buckets = ["workflow-process", "data-document-artifact"]
            else:
                candidate_buckets = ["unclassified"]
        obj["candidate_buckets"] = unique_preserve(candidate_buckets)
        obj["candidate_primary_bucket"] = obj.get("candidate_primary_bucket") or obj["candidate_buckets"][0]
        obj.setdefault("ambiguity_status", "unresolved")
        if not obj.get("candidate_senses"):
            normalized = obj.get("normalized_form") or slug(obj.get("observed_text", "concept"))
            obj["candidate_senses"] = [{
                "sense_id": f"{normalized}#sense-1",
                "label": obj.get("observed_text") or normalized,
                "status": "candidate",
                "candidate_buckets": obj["candidate_buckets"],
            }]
        write_json(path, obj)


def slow_repo_annotations(repo_timings):
    return [item for item in repo_timings if item.get("elapsed_seconds", 0) >= SLOW_REPO_THRESHOLD_SECONDS]


def concept_sort_key(obj):
    return (obj.get("concept_id") or "", obj.get("canonical_name") or "")


def observation_sort_key(obj):
    return (obj.get("concept_id") or "", obj.get("observation_id") or "")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def build_embedding_units(concepts_dir, observations_dir):
    concept_paths = sorted(concepts_dir.glob("*.json"))
    observation_paths = sorted(observations_dir.glob("*.json"))
    concepts = [json.loads(path.read_text()) for path in concept_paths]
    observations = [json.loads(path.read_text()) for path in observation_paths]

    units = []
    for concept in sorted(concepts, key=concept_sort_key):
        concept_id = concept.get("concept_id")
        canonical_name = concept.get("canonical_name") or concept_id
        units.append({
            "unit_id": f"concept:{concept_id}",
            "concept_id": concept_id,
            "unit_kind": "concept",
            "text_for_embedding": canonical_name,
            "metadata": {
                "canonical_name": canonical_name,
                "primary_bucket": concept.get("primary_bucket"),
                "buckets": concept.get("buckets", []),
                "ambiguity_status": concept.get("ambiguity_status"),
                "aliases": sorted(concept.get("aliases", [])),
                "possible_senses": concept.get("possible_senses", []),
            },
        })
        for alias in sorted(set(concept.get("aliases", []))):
            units.append({
                "unit_id": f"concept-alias:{concept_id}:{slug(alias)}",
                "concept_id": concept_id,
                "unit_kind": "concept-alias",
                "text_for_embedding": alias,
                "metadata": {
                    "canonical_name": canonical_name,
                    "primary_bucket": concept.get("primary_bucket"),
                    "buckets": concept.get("buckets", []),
                    "ambiguity_status": concept.get("ambiguity_status"),
                },
            })
        for sense in concept.get("possible_senses", []):
            units.append({
                "unit_id": f"concept-sense:{sense.get('sense_id')}",
                "concept_id": concept_id,
                "unit_kind": "concept-sense",
                "text_for_embedding": sense.get("label") or canonical_name,
                "metadata": {
                    "sense_id": sense.get("sense_id"),
                    "sense_status": sense.get("status"),
                    "buckets": sense.get("buckets", concept.get("buckets", [])),
                    "canonical_name": canonical_name,
                },
            })

    for observation in sorted(observations, key=observation_sort_key):
        units.append({
            "unit_id": f"observation:{observation.get('observation_id')}",
            "concept_id": observation.get("concept_id"),
            "unit_kind": "observation",
            "text_for_embedding": observation.get("observed_text") or observation.get("normalized_form"),
            "metadata": {
                "observation_id": observation.get("observation_id"),
                "observation_kind": observation.get("observation_kind"),
                "candidate_primary_bucket": observation.get("candidate_primary_bucket"),
                "candidate_buckets": observation.get("candidate_buckets", []),
                "ambiguity_status": observation.get("ambiguity_status"),
                "source_repo": observation.get("source_repo"),
                "source_file": observation.get("source_file"),
            },
        })
    units.sort(key=lambda row: (row["concept_id"] or "", row["unit_kind"], row["unit_id"]))
    return units


def build_symbolic_indexes(concepts_dir, observations_dir):
    concept_paths = sorted(concepts_dir.glob("*.json"))
    observation_paths = sorted(observations_dir.glob("*.json"))
    concepts = [json.loads(path.read_text()) for path in concept_paths]
    observations = [json.loads(path.read_text()) for path in observation_paths]

    concepts_by_alias = {}
    concepts_by_bucket = {}
    observations_by_concept = {}

    for concept in sorted(concepts, key=concept_sort_key):
        concept_id = concept.get("concept_id")
        for alias in set(concept.get("aliases", []) + [concept.get("canonical_name")]):
            if not alias:
                continue
            key = alias.casefold()
            concepts_by_alias.setdefault(key, [])
            if concept_id not in concepts_by_alias[key]:
                concepts_by_alias[key].append(concept_id)
        for bucket in concept.get("buckets", []):
            concepts_by_bucket.setdefault(bucket, [])
            if concept_id not in concepts_by_bucket[bucket]:
                concepts_by_bucket[bucket].append(concept_id)

    for observation in sorted(observations, key=observation_sort_key):
        concept_id = observation.get("concept_id")
        observation_id = observation.get("observation_id")
        observations_by_concept.setdefault(concept_id, [])
        if observation_id not in observations_by_concept[concept_id]:
            observations_by_concept[concept_id].append(observation_id)

    return {
        "concepts_by_alias": {k: sorted(v) for k, v in sorted(concepts_by_alias.items())},
        "concepts_by_bucket": {k: sorted(v) for k, v in sorted(concepts_by_bucket.items())},
        "observations_by_concept": {k: sorted(v) for k, v in sorted(observations_by_concept.items())},
    }


def dedupe_edges(edges):
    seen = set()
    out = []
    for edge in edges:
        key = (edge.get('source_repo'), edge.get('target'), edge.get('target_type'), edge.get('edge_type'), edge.get('source_file'))
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def load_json(path):
    return json.loads(Path(path).read_text())


def env_int(name, default):
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(0, value)


def budget_state():
    budget_seconds = env_int("DISCOVERY_BUDGET_SECONDS", DEFAULT_DISCOVERY_BUDGET_SECONDS)
    min_repo_start_seconds = env_int("DISCOVERY_MIN_REPO_START_SECONDS", DEFAULT_DISCOVERY_MIN_REPO_START_SECONDS)
    hard_stop_seconds = env_int("DISCOVERY_HARD_STOP_SECONDS", DEFAULT_DISCOVERY_HARD_STOP_SECONDS)
    started_monotonic = time.monotonic()
    return {
        "budget_seconds": budget_seconds,
        "min_repo_start_seconds": min_repo_start_seconds,
        "hard_stop_seconds": hard_stop_seconds,
        "started_monotonic": started_monotonic,
    }


def elapsed_seconds(budget):
    return time.monotonic() - budget["started_monotonic"]


def remaining_seconds(budget):
    return max(0.0, budget["budget_seconds"] - elapsed_seconds(budget))


def should_stop_before_repo(budget):
    return remaining_seconds(budget) < budget["min_repo_start_seconds"]


def past_hard_stop(budget):
    return remaining_seconds(budget) < budget["hard_stop_seconds"]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def upsert_entity(path, payload, key):
    now = payload["last_seen_at"]
    if path.exists():
        existing = json.loads(path.read_text())
        existing["last_seen_at"] = now
        existing.setdefault("sources", [])
        if payload["sources"][0] not in existing["sources"]:
            existing["sources"].append(payload["sources"][0])
        write_json(path, existing)
    else:
        payload["first_seen_at"] = now
        write_json(path, payload)


def prune_invalid_term_artifacts(terms_dir):
    for path in terms_dir.glob("*.json"):
        try:
            existing = json.loads(path.read_text())
        except Exception:
            path.unlink(missing_ok=True)
            continue
        term = existing.get("term")
        sources = existing.get("sources", [])
        if sources and all(source.get("discovered_via") == "inline-code" for source in sources):
            path.unlink(missing_ok=True)
            continue
        if not term or normalize_term(term) is None:
            path.unlink(missing_ok=True)


def load_frontier(data_root, seeds):
    frontier_file = data_root / "data" / "frontier" / "repos.json"
    if frontier_file.exists():
        data = json.loads(frontier_file.read_text())
        pending = dedupe_frontier_entries(data.get("pending", []))
        processed = []
        seen_processed = set()
        for full_name in data.get("processed", []):
            canonical = canonicalize_repo_full_name(full_name, lowercase=True)
            if not canonical or canonical in seen_processed:
                continue
            seen_processed.add(canonical)
            processed.append(canonical)
        data["pending"] = pending
        data["processed"] = processed
        if pending:
            return pending, data
    pending = dedupe_frontier_entries([
        {"full_name": repo, "graph_distance": 0, "discovered_via": "seed"}
        for repo in seeds["seed_repositories"]
    ])
    return pending, {"pending": pending, "processed": [], "generated_at": None}


def collect_repo(owner_repo, limits, known_repo_keys, allow_topic_expansion=True):
    repo = github_repo(owner_repo)
    canonical_owner_repo = canonicalize_repo_full_name(repo.get("full_name") or owner_repo)
    source_repo_key = repo_identity_key(canonical_owner_repo)
    root_items = github_contents(canonical_owner_repo)
    if not isinstance(root_items, list):
        root_items = []

    readme_paths, manifest_paths, workflow_paths = [], [], []
    for item in root_items:
        name = item.get("name", "")
        path = item.get("path", "")
        if item.get("type") == "file":
            if name in README_CANDIDATES:
                readme_paths.append(path)
            if name in MANIFEST_CANDIDATES:
                manifest_paths.append(path)
        if item.get("type") == "dir" and path == ".github":
            try:
                gh_dir = github_contents(canonical_owner_repo, ".github/workflows")
                if isinstance(gh_dir, list):
                    for wf in gh_dir:
                        if wf.get("type") == "file":
                            workflow_paths.append(wf.get("path"))
            except Exception:
                pass

    file_candidates = (readme_paths + manifest_paths + workflow_paths)[: limits["max_file_fetches_per_repo"]]
    fetched_files, term_hits, component_hits, repo_link_hits, edge_records = [], [], [], [], []

    for path in file_candidates:
        try:
            item = github_contents(canonical_owner_repo, path)
            text = decode_content(item)
        except Exception:
            continue
        fetched_files.append({"path": path, "size": len(text)})

        for match in REPO_URL_RE.findall(text):
            canonical = canonicalize_repo_full_name(match, lowercase=True)
            if not canonical or canonical == source_repo_key or canonical in known_repo_keys:
                continue
            if not explicit_repo_exists(canonical):
                continue
            repo_link_hits.append({"full_name": canonical, "source_file": path, "edge_type": "explicit-github-link"})
            edge_records.append({"source_repo": canonical_owner_repo, "target": canonical, "target_type": "repository", "edge_type": "explicit-github-link", "source_file": path})

        if path.startswith(".github/workflows/"):
            for use in re.findall(r"uses:\s*([^\s]+)", text):
                normalized = normalize_component(use)
                if normalized:
                    component_hits.append({"component": normalized, "source_file": path, "edge_type": "workflow-uses"})
                    edge_records.append({"source_repo": canonical_owner_repo, "target": normalized, "target_type": "component", "edge_type": "workflow-uses", "source_file": path})
            workflow_name = re.search(r"^name:\s*(.+)$", text, flags=re.MULTILINE)
            if workflow_name:
                normalized = normalize_term(workflow_name.group(1))
                if normalized:
                    term_hits.append({"term": normalized, "source_file": path, "edge_type": "workflow-name"})
                    edge_records.append({"source_repo": canonical_owner_repo, "target": normalized, "target_type": "term", "edge_type": "workflow-name", "source_file": path})

        if path.endswith("package.json"):
            try:
                pkg = json.loads(text)
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    for dep in (pkg.get(section) or {}):
                        normalized = normalize_component(dep)
                        if normalized:
                            component_hits.append({"component": normalized, "source_file": path, "edge_type": f"package-json:{section}"})
                            edge_records.append({"source_repo": canonical_owner_repo, "target": normalized, "target_type": "component", "edge_type": f"package-json:{section}", "source_file": path})
            except Exception:
                pass

    source_topics = repo.get("topics") or []
    for topic in source_topics:
        normalized_topic_term = normalize_topic(topic)
        if not is_specific_topic(topic):
            continue
        term_hits.append({"term": normalized_topic_term, "source_file": None, "edge_type": "repo-topic"})
        edge_records.append({"source_repo": canonical_owner_repo, "target": normalized_topic_term, "target_type": "term", "edge_type": "repo-topic", "source_file": None})
    source_topic_set = comparable_topic_set(source_topics)

    related, seen_related = [], set()
    owner_counts = {}
    if allow_topic_expansion:
        expanded_topics = [topic for topic in source_topics if is_specific_topic(topic)][: limits["max_topic_expansions_per_repo"]]
    else:
        expanded_topics = []
    for topic in expanded_topics:
        normalized_topic = normalize_topic(topic)
        try:
            result = github_search_repos(f"topic:{normalized_topic}", TOPIC_RESULT_LIMIT)
        except Exception:
            continue
        for item in result.get("items", []):
            full_name = canonicalize_repo_full_name(item.get("full_name", ""), lowercase=True)
            if not full_name or full_name == source_repo_key or full_name in seen_related or full_name in known_repo_keys:
                continue

            candidate_topic_set = comparable_topic_set(item.get("topics", []))
            shared_topics = source_topic_set & candidate_topic_set
            overlap_without_trigger = shared_topics - {normalized_topic}
            if normalized_topic not in shared_topics or not overlap_without_trigger:
                continue

            candidate_owner = full_name.split('/')[0]
            if owner_counts.get(candidate_owner, 0) >= TOPIC_OWNER_CAP_PER_SOURCE:
                continue

            seen_related.add(full_name)
            owner_counts[candidate_owner] = owner_counts.get(candidate_owner, 0) + 1
            related.append({
                "full_name": full_name,
                "html_url": item.get("html_url"),
                "description": item.get("description"),
                "topics": item.get("topics", []),
                "updated_at": item.get("updated_at"),
                "graph_distance": 1,
                "discovered_via": f"topic:{normalized_topic}",
            })
            edge_records.append({"source_repo": canonical_owner_repo, "target": full_name, "target_type": "repository", "edge_type": f"topic:{normalized_topic}", "source_file": None})
            if len(related) >= limits["max_related_repositories"]:
                break
        if len(related) >= limits["max_related_repositories"]:
            break

    repo_link_hits = [dict(t) for t in {tuple(sorted(hit.items())) for hit in repo_link_hits}]
    repo_link_hits, edge_records = limit_repo_links(repo_link_hits, edge_records, limits["max_repo_links_per_repo"])
    edge_records = dedupe_edges(edge_records)

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "full_name": canonical_owner_repo,
            "html_url": repo.get("html_url"),
            "description": repo.get("description"),
            "topics": repo.get("topics", []),
            "updated_at": repo.get("updated_at"),
            "pushed_at": repo.get("pushed_at"),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
        },
        "fetched_files": fetched_files,
        "terms": term_hits,
        "components": component_hits,
        "repo_links": repo_link_hits,
        "related_repositories": related,
        "edges": edge_records,
    }


def main():
    if len(sys.argv) != 4:
        print("usage: github_seed_discovery.py <seed_json> <limits_json> <output_dir>", file=sys.stderr)
        sys.exit(1)

    seeds = load_json(sys.argv[1])
    limits = load_json(sys.argv[2])
    data_root = Path(sys.argv[3])

    pending, frontier_state = load_frontier(data_root, seeds)
    to_process = pending[: limits["max_frontier_repositories_per_run"]]
    remaining = pending[limits["max_frontier_repositories_per_run"] :]

    repos_dir = data_root / "data" / "discovery" / "repos"
    terms_dir = data_root / "data" / "discovery" / "terms"
    concepts_dir = data_root / "data" / "discovery" / "concepts"
    concept_observations_dir = data_root / "data" / "discovery" / "concept-observations"
    indexes_dir = data_root / "data" / "discovery" / "indexes"
    derived_dir = data_root / "data" / "derived"
    comps_dir = data_root / "data" / "discovery" / "components"
    edges_dir = data_root / "data" / "discovery" / "edges"
    frontier_dir = data_root / "data" / "frontier"
    runs_dir = data_root / "data" / "runs"
    for d in [repos_dir, terms_dir, concepts_dir, concept_observations_dir, indexes_dir, derived_dir, comps_dir, edges_dir, frontier_dir, runs_dir]:
        d.mkdir(parents=True, exist_ok=True)
    prune_invalid_term_artifacts(terms_dir)

    generated_at = datetime.now(timezone.utc).isoformat()
    upsert_seeded_language_concepts(concepts_dir, generated_at)
    normalize_existing_concept_artifacts(concepts_dir)
    normalize_existing_concept_observations(concept_observations_dir)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    budget = budget_state()
    newly_discovered = []
    processed_names = []
    processed_history, known_repo_keys = build_processed_history(frontier_state, processed_names)

    skipped_repositories = []
    stopped_due_to_budget = False
    deferred_entries = []
    repo_timings = []

    for index, entry in enumerate(to_process):
        if should_stop_before_repo(budget):
            stopped_due_to_budget = True
            deferred_entries = to_process[index:]
            break
        repo_started = time.monotonic()
        owner_repo = canonicalize_repo_full_name(entry["full_name"], lowercase=True)
        if not owner_repo or not is_valid_repo_full_name(owner_repo):
            skipped_repositories.append({
                "full_name": entry.get("full_name"),
                "reason": "invalid_repo_full_name",
                "discovered_via": entry.get("discovered_via"),
            })
            continue

        try:
            allow_topic_expansion = (
                not entry.get("discovered_via", "").startswith("topic:")
                and entry.get("graph_distance", 0) <= 1
            )
            data = collect_repo(owner_repo, limits, known_repo_keys, allow_topic_expansion=allow_topic_expansion)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                skipped_repositories.append({
                    "full_name": owner_repo,
                    "reason": "repo_not_found",
                    "discovered_via": entry.get("discovered_via"),
                })
                continue
            raise

        canonical_owner_repo = canonicalize_repo_full_name(data["repo"]["full_name"] or owner_repo, lowercase=True)
        repo_elapsed = round(time.monotonic() - repo_started, 3)
        repo_timings.append({
            "full_name": canonical_owner_repo,
            "elapsed_seconds": repo_elapsed,
            "discovered_via": entry.get("discovered_via"),
            "graph_distance": entry.get("graph_distance"),
        })
        write_json(repos_dir / f"{slug(canonical_owner_repo)}.json", data)
        write_json(edges_dir / f"{slug(canonical_owner_repo)}.json", {"source_repo": data["repo"]["full_name"], "generated_at": generated_at, "edges": data["edges"]})
        if canonical_owner_repo not in known_repo_keys:
            known_repo_keys.add(canonical_owner_repo)
            processed_names.append(canonical_owner_repo)

        for hit in data["terms"]:
            term = hit["term"]
            path = terms_dir / f"{slug(term)}.json"
            upsert_entity(path, {
                "term": term,
                "last_seen_at": generated_at,
                "sources": [{"source_repo": data["repo"]["full_name"], "source_file": hit["source_file"], "discovered_via": hit["edge_type"]}],
            }, "term")
            upsert_concept_observation(concept_observations_dir, generated_at, data["repo"]["full_name"], hit)
            upsert_concept(concepts_dir, generated_at, data["repo"]["full_name"], hit)

        for hit in data["components"]:
            component = hit["component"]
            path = comps_dir / f"{slug(component)}.json"
            upsert_entity(path, {
                "component": component,
                "last_seen_at": generated_at,
                "sources": [{"source_repo": data["repo"]["full_name"], "source_file": hit["source_file"], "discovered_via": hit["edge_type"]}],
            }, "component")

        for rel in data["related_repositories"]:
            newly_discovered.append(rel)
        for link in data["repo_links"]:
            newly_discovered.append({
                "full_name": link["full_name"],
                "graph_distance": entry.get("graph_distance", 0) + 1,
                "discovered_via": link["edge_type"],
            })

        if past_hard_stop(budget):
            stopped_due_to_budget = True
            deferred_entries = to_process[index + 1 :]
            break

    processed_history, known_repo_keys = build_processed_history(frontier_state, processed_names)
    next_pending = dedupe_frontier_entries(deferred_entries + remaining + newly_discovered)
    next_pending = [
        item for item in next_pending
        if repo_identity_key(item.get("full_name")) not in known_repo_keys
    ]

    new_frontier = {
        "generated_at": generated_at,
        "processed": processed_history,
        "pending": next_pending,
    }
    write_json(frontier_dir / "repos.json", new_frontier)

    embedding_units = build_embedding_units(concepts_dir, concept_observations_dir)
    write_jsonl(derived_dir / "embedding-units.jsonl", embedding_units)
    symbolic_indexes = build_symbolic_indexes(concepts_dir, concept_observations_dir)
    write_json(indexes_dir / "concepts-by-alias.json", symbolic_indexes["concepts_by_alias"])
    write_json(indexes_dir / "concepts-by-bucket.json", symbolic_indexes["concepts_by_bucket"])
    write_json(indexes_dir / "observations-by-concept.json", symbolic_indexes["observations_by_concept"])

    run_summary = {
        "run_id": run_id,
        "generated_at": generated_at,
        "processed_repositories": processed_names,
        "skipped_repositories": skipped_repositories,
        "remaining_frontier": len(next_pending),
        "elapsed_seconds": round(elapsed_seconds(budget), 3),
        "budget_seconds": budget["budget_seconds"],
        "remaining_budget_seconds": round(remaining_seconds(budget), 3),
        "stopped_due_to_budget": stopped_due_to_budget,
        "repo_timing_summary": summarize_repo_timings(repo_timings),
        "slow_repo_threshold_seconds": SLOW_REPO_THRESHOLD_SECONDS,
        "slow_repositories": slow_repo_annotations(repo_timings),
        "repo_timings": repo_timings,
        "embedding_unit_count": len(embedding_units),
        "concept_index_counts": {
            "aliases": len(symbolic_indexes["concepts_by_alias"]),
            "buckets": len(symbolic_indexes["concepts_by_bucket"]),
            "observations_by_concept": len(symbolic_indexes["observations_by_concept"]),
        },
    }
    write_json(runs_dir / f"{run_id}.json", run_summary)
    print(json.dumps(run_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
