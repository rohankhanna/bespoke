#!/usr/bin/env python3
import base64
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = "https://api.github.com"
UA = "bespoke-cli-discovery"
REPO_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)")
MANIFEST_CANDIDATES = ["pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod", "Dockerfile"]
README_CANDIDATES = ["README.md", "README.rst", "README.txt"]
TOPIC_SKIP = {"ai", "llm", "python", "javascript", "typescript"}
TOPIC_RESULT_LIMIT = 5
TOPIC_OWNER_CAP_PER_SOURCE = 1


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
    if re.fullmatch(r"[-=:_./\\]+", text):
        return None
    if re.search(r"[{}\[\]<>]", text):
        return None
    if text.startswith((".", "-", "_")):
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
        normalized_entry = dict(entry)
        normalized_entry["full_name"] = canonical
        if canonical in deduped:
            deduped[canonical] = merge_frontier_entries(deduped[canonical], normalized_entry)
        else:
            deduped[canonical] = normalized_entry
            ordered_keys.append(canonical)
    return [deduped[key] for key in ordered_keys]


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


def collect_repo(owner_repo, limits, allow_topic_expansion=True):
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
            if not canonical or canonical == source_repo_key:
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

        for inline in re.findall(r"`([^`]{2,80})`", text):
            if "/" in inline or len(inline.split()) > 6:
                continue
            normalized = normalize_term(inline)
            if normalized:
                term_hits.append({"term": normalized, "source_file": path, "edge_type": "inline-code"})
                edge_records.append({"source_repo": canonical_owner_repo, "target": normalized, "target_type": "term", "edge_type": "inline-code", "source_file": path})

    source_topics = repo.get("topics") or []
    source_topic_set = comparable_topic_set(source_topics)
    source_owner = source_repo_key.split('/')[0] if source_repo_key else None

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
            if not full_name or full_name == source_repo_key or full_name in seen_related:
                continue

            candidate_topic_set = comparable_topic_set(item.get("topics", []))
            shared_topics = source_topic_set & candidate_topic_set
            if normalized_topic not in shared_topics:
                continue

            overlap_without_trigger = shared_topics - {normalized_topic}
            candidate_owner = full_name.split('/')[0]
            if not overlap_without_trigger and candidate_owner != source_owner:
                continue
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

    edge_records = dedupe_edges(edge_records)
    repo_link_hits = [dict(t) for t in {tuple(sorted(hit.items())) for hit in repo_link_hits}]

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
    comps_dir = data_root / "data" / "discovery" / "components"
    edges_dir = data_root / "data" / "discovery" / "edges"
    frontier_dir = data_root / "data" / "frontier"
    runs_dir = data_root / "data" / "runs"
    for d in [repos_dir, terms_dir, comps_dir, edges_dir, frontier_dir, runs_dir]:
        d.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    newly_discovered = []
    processed_names = []
    processed_keys = set()

    skipped_repositories = []

    for entry in to_process:
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
            data = collect_repo(owner_repo, limits, allow_topic_expansion=allow_topic_expansion)
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
        write_json(repos_dir / f"{slug(canonical_owner_repo)}.json", data)
        write_json(edges_dir / f"{slug(canonical_owner_repo)}.json", {"source_repo": data["repo"]["full_name"], "generated_at": generated_at, "edges": data["edges"]})
        if canonical_owner_repo not in processed_keys:
            processed_keys.add(canonical_owner_repo)
            processed_names.append(canonical_owner_repo)

        for hit in data["terms"]:
            term = hit["term"]
            path = terms_dir / f"{slug(term)}.json"
            upsert_entity(path, {
                "term": term,
                "last_seen_at": generated_at,
                "sources": [{"source_repo": data["repo"]["full_name"], "source_file": hit["source_file"], "discovered_via": hit["edge_type"]}],
            }, "term")

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

    next_pending = dedupe_frontier_entries(remaining + newly_discovered)
    next_pending = [
        item for item in next_pending
        if repo_identity_key(item.get("full_name")) not in processed_keys
    ]

    processed_history = []
    seen_processed = set()
    for full_name in frontier_state.get("processed", []) + processed_names:
        canonical = repo_identity_key(full_name)
        if not canonical or canonical in seen_processed:
            continue
        seen_processed.add(canonical)
        processed_history.append(canonical)

    new_frontier = {
        "generated_at": generated_at,
        "processed": processed_history,
        "pending": next_pending,
    }
    write_json(frontier_dir / "repos.json", new_frontier)

    run_summary = {
        "run_id": run_id,
        "generated_at": generated_at,
        "processed_repositories": processed_names,
        "skipped_repositories": skipped_repositories,
        "remaining_frontier": len(next_pending),
    }
    write_json(runs_dir / f"{run_id}.json", run_summary)
    print(json.dumps(run_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
