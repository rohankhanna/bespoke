import importlib.util
import json
import sys
from pathlib import Path
from urllib.error import HTTPError


def load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "github_seed_discovery.py"
    spec = importlib.util.spec_from_file_location("github_seed_discovery", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_transient_http_errors_are_summarized():
    module = load_module()
    error = HTTPError(
        url="https://api.github.com/repos/example/repo",
        code=403,
        msg="Forbidden",
        hdrs={"Retry-After": "60", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1710000000"},
        fp=None,
    )

    assert module.is_transient_github_http_error(error) is True
    assert module.summarize_github_http_error(error) == {
        "url": "https://api.github.com/repos/example/repo",
        "http_status": 403,
        "reason": "Forbidden",
        "retry_after": "60",
        "rate_limit_remaining": "0",
        "rate_limit_reset": "1710000000",
    }


def test_main_converts_transient_api_error_into_checkpointed_stop(tmp_path, monkeypatch):
    module = load_module()

    seed_path = tmp_path / "seed.json"
    limits_path = tmp_path / "limits.json"
    data_root = tmp_path / "out"
    seed_path.write_text(json.dumps({"seed_repositories": ["owner/repo"]}))
    limits_path.write_text(
        json.dumps(
            {
                "max_frontier_repositories_per_run": 20,
                "max_topic_expansions_per_repo": 5,
                "max_related_repositories": 20,
                "max_file_fetches_per_repo": 10,
                "max_repo_links_per_repo": 4,
            }
        )
    )

    pending = [{"full_name": "owner/repo", "graph_distance": 0, "discovered_via": "seed"}]
    monkeypatch.setattr(module, "load_frontier", lambda data_root, seeds: (pending, {"pending": pending, "processed": [], "generated_at": None}))
    monkeypatch.setattr(module, "upsert_seeded_language_concepts", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "normalize_existing_concept_artifacts", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "normalize_existing_concept_observations", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "build_embedding_units", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        module,
        "build_symbolic_indexes",
        lambda *args, **kwargs: {
            "concepts_by_alias": {},
            "concepts_by_bucket": {},
            "observations_by_concept": {},
        },
    )

    error = HTTPError(
        url="https://api.github.com/repos/owner/repo",
        code=403,
        msg="Forbidden",
        hdrs={"Retry-After": "60", "X-RateLimit-Remaining": "0"},
        fp=None,
    )
    monkeypatch.setattr(module, "collect_repo", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    old_argv = sys.argv
    sys.argv = [
        "github_seed_discovery.py",
        str(seed_path),
        str(limits_path),
        str(data_root),
    ]
    try:
        module.main()
    finally:
        sys.argv = old_argv

    run_files = sorted((data_root / "data" / "runs").glob("*.json"))
    assert len(run_files) == 1
    summary = json.loads(run_files[0].read_text())
    assert summary["stopped_due_to_api"] is True
    assert summary["stop_reason"] == "github_api_error"
    assert summary["api_stop_detail"]["full_name"] == "owner/repo"
    assert summary["remaining_frontier"] == 1

    frontier = json.loads((data_root / "data" / "frontier" / "repos.json").read_text())
    assert frontier["pending"][0]["full_name"] == "owner/repo"
