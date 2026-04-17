#!/usr/bin/env python3
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = "https://api.github.com"
UA = "bespoke-cli-discovery"
REPO_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
MANIFEST_CANDIDATES = ["pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod", "Dockerfile"]
README_CANDIDATES = ["README.md", "README.rst", "README.txt"]


def api_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def github_repo(owner_repo):
    return api_get_json(f"{API_ROOT}/repos/{owner_repo}")


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


def load_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_frontier(data_root, seeds):
    frontier_file = data_root / "data" / "frontier" / "repos.json"
    if frontier_file.exists():
        data = json.loads(frontier_file.read_text())
        pending = data.get("pending", [])
        if pending:
            return pending, data
    pending = [{"full_name": repo, "graph_distance": 0, "discovered_via": "seed"} for repo in seeds["seed_repositories"]]
    return pending, {"pending": pending, "processed": [], "generated_at": None}


def collect_repo(owner_repo, limits):
    repo = github_repo(owner_repo)
    root_items = github_contents(owner_repo)
    if not isinstance(root_items, list):
        root_items = []

    file_candidates = []
    workflow_paths = []
    readme_paths = []
    manifest_paths = []

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
                gh_dir = github_contents(owner_repo, ".github/workflows")
                if isinstance(gh_dir, list):
                    for wf in gh_dir:
                        if wf.get("type") == "file":
                            workflow_paths.append(wf.get("path"))
            except Exception:
                pass

    file_candidates = (readme_paths + manifest_paths + workflow_paths)[: limits["max_file_fetches_per_repo"]]
    fetched_files = []
    terms = set()
    components = set()
    repo_links = set()

    for path in file_candidates:
        try:
            item = github_contents(owner_repo, path)
            text = decode_content(item)
        except Exception:
            continue
        fetched_files.append({"path": path, "size": len(text)})

        for match in REPO_URL_RE.findall(text):
            repo_links.add(match)

        if path.startswith(".github/workflows/"):
            for use in re.findall(r"uses:\s*([^\s]+)", text):
                components.add(use.strip())
            workflow_name = re.search(r"^name:\s*(.+)$", text, flags=re.MULTILINE)
            if workflow_name:
                terms.add(workflow_name.group(1).strip())

        if path.endswith("package.json"):
            try:
                pkg = json.loads(text)
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    for dep in (pkg.get(section) or {}):
                        components.add(dep)
            except Exception:
                pass

        for inline in re.findall(r"`([^`]{2,80})`", text):
            if "/" in inline or len(inline.split()) > 6:
                continue
            terms.add(inline.strip())

    related = []
    seen_related = set()
    for topic in (repo.get("topics") or [])[: limits["max_topic_expansions_per_repo"]]:
        try:
            result = github_search_repos(f"topic:{topic}", 5)
        except Exception:
            continue
        for item in result.get("items", []):
            full_name = item.get("full_name")
            if not full_name or full_name == owner_repo or full_name in seen_related:
                continue
            seen_related.add(full_name)
            related.append({
                "full_name": full_name,
                "html_url": item.get("html_url"),
                "description": item.get("description"),
                "topics": item.get("topics", []),
                "updated_at": item.get("updated_at"),
                "graph_distance": 1,
                "discovered_via": f"topic:{topic}",
            })
            if len(related) >= limits["max_related_repositories"]:
                break
        if len(related) >= limits["max_related_repositories"]:
            break

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "full_name": repo.get("full_name"),
            "html_url": repo.get("html_url"),
            "description": repo.get("description"),
            "topics": repo.get("topics", []),
            "updated_at": repo.get("updated_at"),
            "pushed_at": repo.get("pushed_at"),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
        },
        "fetched_files": fetched_files,
        "discovered_terms": sorted(terms),
        "discovered_components": sorted(components),
        "discovered_repo_links": sorted(repo_links)[: limits["max_repo_links_per_repo"]],
        "related_repositories": related,
    }


def main():
    if len(sys.argv) != 4:
        print("usage: github_seed_discovery.py <seed_json> <limits_json> <output_dir>", file=sys.stderr)
        sys.exit(1)

    seeds = load_json(sys.argv[1])
    limits = load_json(sys.argv[2])
    output_root = Path(sys.argv[3])
    data_root = output_root

    pending, frontier_state = load_frontier(data_root, seeds)
    to_process = pending[: limits["max_frontier_repositories_per_run"]]
    remaining = pending[limits["max_frontier_repositories_per_run"] :]

    repos_dir = data_root / "data" / "discovery" / "repos"
    terms_dir = data_root / "data" / "discovery" / "terms"
    comps_dir = data_root / "data" / "discovery" / "components"
    frontier_dir = data_root / "data" / "frontier"
    runs_dir = data_root / "data" / "runs"
    for d in [repos_dir, terms_dir, comps_dir, frontier_dir, runs_dir]:
        d.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    newly_discovered = []
    processed_names = []

    for entry in to_process:
        owner_repo = entry["full_name"]
        data = collect_repo(owner_repo, limits)
        write_json(repos_dir / f"{slug(owner_repo)}.json", data)
        processed_names.append(owner_repo)

        for term in data["discovered_terms"]:
            write_json(terms_dir / f"{slug(term)}.json", {
                "term": term,
                "source_repo": owner_repo,
                "discovered_via": "github-hosted-files",
                "first_seen_at": generated_at,
                "last_seen_at": generated_at,
            })

        for component in data["discovered_components"]:
            write_json(comps_dir / f"{slug(component)}.json", {
                "component": component,
                "source_repo": owner_repo,
                "discovered_via": "manifest-or-workflow",
                "first_seen_at": generated_at,
                "last_seen_at": generated_at,
            })

        for rel in data["related_repositories"]:
            newly_discovered.append(rel)
        for link in data["discovered_repo_links"]:
            newly_discovered.append({
                "full_name": link,
                "graph_distance": entry.get("graph_distance", 0) + 1,
                "discovered_via": "explicit-github-link",
            })

    seen = set(remaining_item.get("full_name") for remaining_item in remaining)
    next_pending = list(remaining)
    for item in newly_discovered:
        full_name = item.get("full_name")
        if not full_name or full_name in processed_names or full_name in seen:
            continue
        seen.add(full_name)
        next_pending.append(item)

    new_frontier = {
        "generated_at": generated_at,
        "processed": frontier_state.get("processed", []) + processed_names,
        "pending": next_pending,
    }
    write_json(frontier_dir / "repos.json", new_frontier)

    run_summary = {
        "run_id": run_id,
        "generated_at": generated_at,
        "processed_repositories": processed_names,
        "remaining_frontier": len(next_pending),
    }
    write_json(runs_dir / f"{run_id}.json", run_summary)
    print(json.dumps(run_summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
