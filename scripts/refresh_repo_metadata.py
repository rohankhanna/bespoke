#!/usr/bin/env python3
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = "https://api.github.com"
UA = "bespoke-cli-metadata-refresh"
DEFAULT_REFRESH_LIMIT = 200
DEFAULT_REFRESH_BUDGET_SECONDS = 1800
DEFAULT_REFRESH_MIN_START_SECONDS = 20
DEFAULT_REFRESH_HARD_STOP_SECONDS = 10


def api_get_json(url):
    headers = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def env_int(name, default):
    raw = os.getenv(name)
    if raw in (None, ""):
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def budget_state():
    return {
        "budget_seconds": env_int("METADATA_REFRESH_BUDGET_SECONDS", DEFAULT_REFRESH_BUDGET_SECONDS),
        "min_start_seconds": env_int("METADATA_REFRESH_MIN_START_SECONDS", DEFAULT_REFRESH_MIN_START_SECONDS),
        "hard_stop_seconds": env_int("METADATA_REFRESH_HARD_STOP_SECONDS", DEFAULT_REFRESH_HARD_STOP_SECONDS),
        "started_monotonic": time.monotonic(),
    }


def elapsed_seconds(budget):
    return time.monotonic() - budget["started_monotonic"]


def remaining_seconds(budget):
    return max(0.0, budget["budget_seconds"] - elapsed_seconds(budget))


def should_stop_before_next(budget):
    return remaining_seconds(budget) < budget["min_start_seconds"]


def past_hard_stop(budget):
    return remaining_seconds(budget) < budget["hard_stop_seconds"]


def canonical_repo(full_name):
    return (full_name or "").strip().lower()


def repo_sort_key(wrapper):
    repo = wrapper.get("repo") or {}
    stars = repo.get("stargazers_count")
    updated = repo.get("updated_at") or repo.get("pushed_at") or ""
    return (
        0 if stars is None else 1,
        updated,
        canonical_repo(repo.get("full_name")),
    )


def github_repo(owner_repo):
    return api_get_json(f"{API_ROOT}/repos/{owner_repo}")


def refresh_repo_wrapper(path: Path):
    wrapper = load_json(path)
    repo = wrapper.get("repo") or {}
    full_name = canonical_repo(repo.get("full_name"))
    if not full_name:
        return None, "missing_full_name"
    live = github_repo(full_name)
    repo["full_name"] = canonical_repo(live.get("full_name") or full_name)
    repo["html_url"] = live.get("html_url")
    repo["description"] = live.get("description")
    repo["topics"] = live.get("topics", [])
    repo["updated_at"] = live.get("updated_at")
    repo["pushed_at"] = live.get("pushed_at")
    repo["default_branch"] = live.get("default_branch")
    repo["language"] = live.get("language")
    repo["stargazers_count"] = live.get("stargazers_count")
    repo["archived"] = bool(live.get("archived", False))
    repo["fork"] = bool(live.get("fork", False))
    wrapper["repo"] = repo
    wrapper["metadata_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    write_json(path, wrapper)
    return repo["full_name"], None


def main():
    if len(sys.argv) != 2:
        print("usage: refresh_repo_metadata.py <data_root>", file=sys.stderr)
        raise SystemExit(1)
    data_root = Path(sys.argv[1])
    repos_dir = data_root / "data" / "discovery" / "repos"
    runs_dir = data_root / "data" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    refresh_limit = env_int("METADATA_REFRESH_LIMIT", DEFAULT_REFRESH_LIMIT)
    budget = budget_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    generated_at = datetime.now(timezone.utc).isoformat()

    wrappers = []
    for path in sorted(repos_dir.glob("*.json")):
        try:
            wrappers.append((path, load_json(path)))
        except Exception:
            continue
    wrappers.sort(key=lambda item: repo_sort_key(item[1]))

    refreshed = []
    skipped = []
    repo_timings = []
    stopped_due_to_budget = False

    for index, (path, wrapper) in enumerate(wrappers[:refresh_limit]):
        if should_stop_before_next(budget):
            stopped_due_to_budget = True
            skipped.extend(canonical_repo((item[1].get("repo") or {}).get("full_name")) for item in wrappers[index:refresh_limit])
            break
        repo_started = time.monotonic()
        try:
            full_name, error_reason = refresh_repo_wrapper(path)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                skipped.append(canonical_repo(((wrapper.get("repo") or {}).get("full_name"))))
                continue
            raise
        repo_elapsed = round(time.monotonic() - repo_started, 3)
        if error_reason:
            skipped.append(canonical_repo(((wrapper.get("repo") or {}).get("full_name"))))
            continue
        refreshed.append(full_name)
        repo_timings.append({"full_name": full_name, "elapsed_seconds": repo_elapsed})
        if past_hard_stop(budget):
            stopped_due_to_budget = True
            skipped.extend(canonical_repo((item[1].get("repo") or {}).get("full_name")) for item in wrappers[index + 1:refresh_limit])
            break

    summary = {
        "run_id": run_id,
        "generated_at": generated_at,
        "refresh_limit": refresh_limit,
        "refreshed_repositories": refreshed,
        "refreshed_count": len(refreshed),
        "skipped_repositories": [name for name in skipped if name],
        "skipped_count": len([name for name in skipped if name]),
        "elapsed_seconds": round(elapsed_seconds(budget), 3),
        "budget_seconds": budget["budget_seconds"],
        "remaining_budget_seconds": round(remaining_seconds(budget), 3),
        "stopped_due_to_budget": stopped_due_to_budget,
        "repo_timings": repo_timings,
    }
    write_json(runs_dir / f"metadata-refresh-{run_id}.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
