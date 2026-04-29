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
        "rate_limit_resource": None,
    }


def test_rate_limit_kind_primary_when_remaining_is_zero():
    module = load_module()
    error = HTTPError(
        url="https://api.github.com/repos/example/repo",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1710000000", "X-RateLimit-Resource": "core"},
        fp=None,
    )

    assert module.classify_rate_limit_error(error) == "primary"


def test_rate_limit_kind_secondary_when_retry_after_present_without_zero_remaining():
    module = load_module()
    error = HTTPError(
        url="https://api.github.com/repos/example/repo",
        code=403,
        msg="You have exceeded a secondary rate limit",
        hdrs={"Retry-After": "60", "X-RateLimit-Remaining": "12", "X-RateLimit-Resource": "core"},
        fp=None,
    )

    assert module.classify_rate_limit_error(error) == "secondary"


def test_forbidden_with_remaining_quota_and_reset_header_is_not_rate_limit():
    module = load_module()
    error = HTTPError(
        url="https://api.github.com/repos/gautamkrishnar/keepalive-workflow",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "4991", "X-RateLimit-Reset": "1777426698", "X-RateLimit-Resource": "core"},
        fp=None,
    )

    assert module.is_rate_limit_http_error(error) is False
    assert module.classify_rate_limit_error(error) == "not_rate_limited"
    assert module.is_transient_github_http_error(error) is False


def test_api_get_json_does_not_backoff_for_forbidden_with_remaining_quota(monkeypatch):
    module = load_module()
    sleeps = []
    error = HTTPError(
        url="https://api.github.com/repos/gautamkrishnar/keepalive-workflow",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "4991", "X-RateLimit-Reset": "1777426698", "X-RateLimit-Resource": "core"},
        fp=None,
    )

    def fake_urlopen(req, timeout=30):
        raise error

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    try:
        module.api_get_json("https://api.github.com/repos/gautamkrishnar/keepalive-workflow")
    except HTTPError as exc:
        assert exc is error
    else:
        raise AssertionError("expected HTTPError")

    assert sleeps == []


def test_api_get_json_retries_rate_limit_and_resets_backoff(monkeypatch):
    module = load_module()

    sleeps = []
    module.RATE_LIMIT_BACKOFF_SECONDS = 0

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    rate_limited = HTTPError(
        url="https://api.github.com/repos/example/repo",
        code=403,
        msg="Forbidden",
        hdrs={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1710009999"},
        fp=None,
    )
    responses = [rate_limited, FakeResponse({"ok": True})]

    def fake_urlopen(req, timeout=30):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(module.time, "time", lambda: 1710000000)

    result = module.api_get_json("https://api.github.com/repos/example/repo")

    assert result == {"ok": True}
    assert sleeps == [1]
    assert module.RATE_LIMIT_BACKOFF_SECONDS == 0


def test_api_get_json_backoff_grows_exponentially_until_success(monkeypatch):
    module = load_module()

    sleeps = []
    module.RATE_LIMIT_BACKOFF_SECONDS = 0

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    responses = [
        HTTPError(
            url="https://api.github.com/repos/example/repo",
            code=403,
            msg="Forbidden",
            hdrs={"X-RateLimit-Remaining": "0"},
            fp=None,
        ),
        HTTPError(
            url="https://api.github.com/repos/example/repo",
            code=429,
            msg="Too Many Requests",
            hdrs={"X-RateLimit-Remaining": "0"},
            fp=None,
        ),
        FakeResponse({"ok": True}),
    ]

    def fake_urlopen(req, timeout=30):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = module.api_get_json("https://api.github.com/repos/example/repo")

    assert result == {"ok": True}
    assert sleeps == [1, 2]
    assert module.RATE_LIMIT_BACKOFF_SECONDS == 0


def test_main_skips_transient_api_error_for_non_rate_limit_403(tmp_path, monkeypatch):
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
        hdrs={},
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
    assert summary["stopped_due_to_api"] is False
    assert summary["stop_reason"] is None
    assert summary["processed_repositories"] == []
    assert len(summary["skipped_repositories"]) == 1
    assert summary["skipped_repositories"][0]["reason"] == "repo_access_forbidden"
    assert summary["remaining_frontier"] == 0

    frontier = json.loads((data_root / "data" / "frontier" / "repos.json").read_text())
    assert frontier["pending"] == []
