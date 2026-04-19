#!/usr/bin/env python3
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

FACET_VERSION = 1
UPDATED_BUCKETS = [
    ("updated_0_1d", timedelta(days=1), "Updated in the last 24 hours"),
    ("updated_1_7d", timedelta(days=7), "Updated 1 to 7 days ago"),
    ("updated_8_14d", timedelta(days=14), "Updated 8 to 14 days ago"),
    ("updated_15_30d", timedelta(days=30), "Updated 15 to 30 days ago"),
    ("updated_31_60d", timedelta(days=60), "Updated 31 to 60 days ago"),
    ("updated_61_90d", timedelta(days=90), "Updated 61 to 90 days ago"),
    ("updated_91_180d", timedelta(days=180), "Updated 91 to 180 days ago"),
]
UPDATED_FALLBACK = ("updated_181d_plus", "Updated more than 180 days ago")

STAR_BUCKETS = [
    ("stars_unknown", None, None, "Unknown stars"),
    ("stars_0", 0, 0, "0 stars"),
    ("stars_1_9", 1, 9, "1 to 9 stars"),
    ("stars_10_99", 10, 99, "10 to 99 stars"),
    ("stars_100_999", 100, 999, "100 to 999 stars"),
    ("stars_1000_9999", 1000, 9999, "1,000 to 9,999 stars"),
    ("stars_10000_99999", 10000, 99999, "10,000 to 99,999 stars"),
    ("stars_100000_999999", 100000, 999999, "100,000 to 999,999 stars"),
    ("stars_1000000_plus", 1000000, None, "1,000,000+ stars"),
]

LANGUAGE_LABELS = {
    "python": "Python",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "c_cpp": "C/C++",
    "shell": "Shell",
    "other": "Other",
    "unknown": "Unknown",
}
LANGUAGE_ORDER = [
    "python",
    "typescript",
    "javascript",
    "go",
    "rust",
    "java",
    "c_cpp",
    "shell",
    "other",
    "unknown",
]
PRODUCT_SURFACE_ORDER = [
    "cli",
    "library",
    "framework",
    "service_api",
    "web_app",
    "infra_tooling",
    "template_starter",
    "docs_knowledge",
    "model_or_data",
    "unknown",
]
PRODUCT_SURFACE_LABELS = {
    "cli": "CLI",
    "library": "Library",
    "framework": "Framework",
    "service_api": "Service/API",
    "web_app": "Web app",
    "infra_tooling": "Infrastructure/tooling",
    "template_starter": "Template/starter",
    "docs_knowledge": "Docs/knowledge",
    "model_or_data": "Model/data",
    "unknown": "Unknown",
}


def load_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def parse_iso(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def canonical_repo(full_name):
    return (full_name or "").strip().lower()


def slug_label(key):
    return key.replace("_", "-")


def normalize_language(language):
    if language is None:
        return "unknown"
    value = str(language).strip().lower()
    if not value:
        return "unknown"
    mapping = {
        "python": "python",
        "typescript": "typescript",
        "javascript": "javascript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "shell": "shell",
        "bash": "shell",
        "shellscript": "shell",
        "c": "c_cpp",
        "c++": "c_cpp",
        "cpp": "c_cpp",
        "objective-c": "c_cpp",
        "objective-c++": "c_cpp",
    }
    return mapping.get(value, "other")


def updated_bucket(repo, now):
    updated_at = parse_iso(repo.get("pushed_at") or repo.get("updated_at"))
    if updated_at is None:
        return UPDATED_FALLBACK[0]
    age = now - updated_at
    previous = timedelta(seconds=0)
    for key, upper, _label in UPDATED_BUCKETS:
        if previous <= age <= upper:
            return key
        previous = upper
    return UPDATED_FALLBACK[0]


def star_bucket(repo):
    stars = repo.get("stargazers_count")
    if stars is None:
        return "stars_unknown"
    for key, minimum, maximum, _label in STAR_BUCKETS:
        if minimum is None and maximum is None:
            continue
        if maximum is None:
            if stars >= minimum:
                return key
        elif minimum <= stars <= maximum:
            return key
    return STAR_BUCKETS[1][0]


def classify_product_surface(repo_wrapper):
    repo = repo_wrapper.get("repo") or {}
    description = (repo.get("description") or "").lower()
    components = [str(item.get("component") or "").lower() for item in repo_wrapper.get("components") or []]
    fetched_files = [str(path).lower() for path in repo_wrapper.get("fetched_files") or []]
    topics = [str(topic).lower() for topic in repo.get("topics") or []]

    def has_any(haystack, needles):
        return any(needle in item for item in haystack for needle in needles)

    if any(token in description for token in ["command line", "cli", "terminal"]) or has_any(topics, ["cli", "terminal"]):
        return "cli"
    if has_any(fetched_files, ["dockerfile", "compose", "terraform", ".github/workflows"]) or has_any(topics, ["devops", "infrastructure", "kubernetes"]):
        return "infra_tooling"
    if has_any(fetched_files, ["package.json"]) and any(token in description for token in ["web", "frontend", "browser", "ui"]):
        return "web_app"
    if any(token in description for token in ["framework", "sdk", "library", "package"]):
        if "framework" in description:
            return "framework"
        return "library"
    if any(token in description for token in ["api", "server", "service"]):
        return "service_api"
    if any(token in description for token in ["template", "starter", "boilerplate"]):
        return "template_starter"
    if any(token in description for token in ["dataset", "model", "checkpoint"]):
        return "model_or_data"
    if any(token in description for token in ["docs", "documentation", "knowledge", "guide"]):
        return "docs_knowledge"
    if fetched_files:
        manifest_names = {Path(path).name.lower() for path in fetched_files}
        if manifest_names & {"pyproject.toml", "cargo.toml", "package.json", "go.mod"}:
            return "library"
    return "unknown"


def load_repo_wrappers(data_root: Path):
    repo_dir = data_root / "data" / "discovery" / "repos"
    wrappers = []
    for path in sorted(repo_dir.glob("*.json")):
        wrapper = load_json(path)
        repo = wrapper.get("repo") or {}
        full_name = repo.get("full_name")
        if not full_name:
            continue
        wrappers.append(wrapper)
    return wrappers


def collect_source_repo_counts(entity_dir: Path, source_key: str, nested_key=None):
    counts = Counter()
    for path in sorted(entity_dir.glob("*.json")):
        obj = load_json(path)
        repos = set()
        if nested_key is None:
            values = obj.get(source_key)
            if isinstance(values, list):
                for item in values:
                    if isinstance(item, dict) and item.get("source_repo"):
                        repos.add(canonical_repo(item.get("source_repo")))
            elif obj.get(source_key):
                repos.add(canonical_repo(obj.get(source_key)))
        else:
            values = obj.get(nested_key) or []
            for item in values:
                if isinstance(item, dict) and item.get(source_key):
                    repos.add(canonical_repo(item.get(source_key)))
        for repo_name in repos:
            counts[repo_name] += 1
    return counts


def build_repo_facts(data_root: Path):
    wrappers = load_repo_wrappers(data_root)
    now = datetime.now(timezone.utc)
    term_counts = collect_source_repo_counts(data_root / "data" / "discovery" / "terms", "sources")
    component_counts = collect_source_repo_counts(data_root / "data" / "discovery" / "components", "sources")
    concept_counts = collect_source_repo_counts(data_root / "data" / "discovery" / "concepts", "source_repo", nested_key="evidence")
    observation_counts = collect_source_repo_counts(data_root / "data" / "discovery" / "concept-observations", "source_repo")

    facts = []
    for wrapper in wrappers:
        repo = wrapper["repo"]
        full_name = repo["full_name"]
        key = canonical_repo(full_name)
        fact = {
            "repo": full_name,
            "repo_key": key,
            "html_url": repo.get("html_url"),
            "description": repo.get("description"),
            "language": repo.get("language"),
            "language_bucket": normalize_language(repo.get("language")),
            "updated_at": repo.get("pushed_at") or repo.get("updated_at"),
            "updated_bucket": updated_bucket(repo, now),
            "stars": repo.get("stargazers_count"),
            "star_bucket": star_bucket(repo),
            "product_surface_bucket": classify_product_surface(wrapper),
            "is_archived": bool(repo.get("archived") or False),
            "is_fork": bool(repo.get("fork") or False),
            "counts": {
                "terms": term_counts.get(key, 0),
                "components": component_counts.get(key, 0),
                "concepts": concept_counts.get(key, 0),
                "observations": observation_counts.get(key, 0),
            },
        }
        facts.append(fact)
    return sorted(facts, key=lambda item: item["repo_key"])


def bucket_metadata():
    updated_labels = {key: label for key, _upper, label in UPDATED_BUCKETS}
    updated_labels[UPDATED_FALLBACK[0]] = UPDATED_FALLBACK[1]
    star_labels = {key: label for key, _minimum, _maximum, label in STAR_BUCKETS}
    return updated_labels, star_labels


def facet_nav(current_updated=None, current_star=None, current_language=None):
    updated_labels, star_labels = bucket_metadata()
    lines = []
    lines.append("Updated buckets: " + " | ".join(
        f"[{updated_labels[key]}](../{'../' if current_language is not None else ''}{slug_label(key)}.md)" if key != current_updated else f"**{updated_labels[key]}**"
        for key in list(updated_labels.keys())
    ))
    lines.append("")
    lines.append("Star buckets: " + " | ".join(
        f"[{star_labels[key]}](../{'../' if current_language is not None else ''}{slug_label(key)}.md)" if key != current_star else f"**{star_labels[key]}**"
        for key in list(star_labels.keys())
    ))
    if current_language is not None:
        lines.append("")
        lines.append("Language buckets: " + " | ".join(
            f"[{LANGUAGE_LABELS[key]}](./{slug_label(key)}.md)" if key != current_language else f"**{LANGUAGE_LABELS[key]}**"
            for key in LANGUAGE_ORDER
        ))
    return "\n".join(lines)


def markdown_table(rows):
    header = "| Repo | Stars | Updated | Language | Product surface | Terms | Components | Concepts | Observations |"
    divider = "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"
    body = []
    for row in rows:
        body.append(
            "| [{repo}]({url}) | {stars} | {updated} | {language} | {surface} | {terms} | {components} | {concepts} | {observations} |".format(
                repo=row["repo"],
                url=row["html_url"] or f"https://github.com/{row['repo']}",
                stars=row["stars"] if row["stars"] is not None else "unknown",
                updated=row["updated_at"] or "unknown",
                language=LANGUAGE_LABELS.get(row["language_bucket"], row["language_bucket"]),
                surface=PRODUCT_SURFACE_LABELS.get(row["product_surface_bucket"], row["product_surface_bucket"]),
                terms=row["counts"]["terms"],
                components=row["counts"]["components"],
                concepts=row["counts"]["concepts"],
                observations=row["counts"]["observations"],
            )
        )
    return "\n".join([header, divider] + body)


def page_payload(filters, rows, generated_at):
    counts = {
        "repos": len(rows),
        "terms": sum(item["counts"]["terms"] for item in rows),
        "components": sum(item["counts"]["components"] for item in rows),
        "concepts": sum(item["counts"]["concepts"] for item in rows),
        "observations": sum(item["counts"]["observations"] for item in rows),
    }
    return {
        "generated_at": generated_at,
        "facet_version": FACET_VERSION,
        "filters": filters,
        "counts": counts,
        "repo_ids": [item["repo"] for item in rows],
    }


def page_markdown(title, filters, rows, generated_at, note=None):
    lines = [f"# {title}", "", f"Generated at: `{generated_at}`", ""]
    if note:
        lines += [note, ""]
    lines += ["## Active filters", ""]
    for key, value in filters.items():
        lines.append(f"- `{key}`: `{value}`")
    payload = page_payload(filters, rows, generated_at)
    lines += ["", "## Counts", ""]
    for key, value in payload["counts"].items():
        lines.append(f"- {key}: {value}")
    if rows:
        latest_sorted = sorted(rows, key=lambda item: (item["updated_at"] or "", item["stars"] or -1, item["repo_key"]), reverse=True)
        star_sorted = sorted(rows, key=lambda item: (item["stars"] if item["stars"] is not None else -1, item["updated_at"] or "", item["repo_key"]), reverse=True)
        lines += ["", "## Static behavior", "", "This is a generated static Markdown page. It has no client-side filtering or sorting. Use linked facet pages for browsing and the precomputed sort sections below for alternate views.", ""]
        lines += ["## Repos sorted by latest update", "", markdown_table(latest_sorted), ""]
        lines += ["## Repos sorted by stars", "", markdown_table(star_sorted), ""]
    else:
        lines += ["", "No repositories matched this slice.", ""]
    return "\n".join(lines)


def build_pages(data_root: Path):
    generated_at = datetime.now(timezone.utc).isoformat()
    facts = build_repo_facts(data_root)
    derived_root = data_root / "data" / "derived" / "discovery-pages"
    markdown_root = derived_root / "markdown"
    write_jsonl(derived_root / "repo-facets.jsonl", facts)

    updated_labels, star_labels = bucket_metadata()
    pages_by_updated = defaultdict(list)
    pages_by_star = defaultdict(list)
    pages_by_language = defaultdict(list)
    pages_matrix = defaultdict(list)
    pages_matrix_language = defaultdict(list)
    for fact in facts:
        pages_by_updated[fact["updated_bucket"]].append(fact)
        pages_by_star[fact["star_bucket"]].append(fact)
        pages_by_language[fact["language_bucket"]].append(fact)
        pages_matrix[(fact["updated_bucket"], fact["star_bucket"])].append(fact)
        pages_matrix_language[(fact["updated_bucket"], fact["star_bucket"], fact["language_bucket"])].append(fact)

    index = {
        "generated_at": generated_at,
        "facet_version": FACET_VERSION,
        "repo_count": len(facts),
        "updated_counts": {key: len(pages_by_updated.get(key, [])) for key in list(updated_labels.keys())},
        "star_counts": {key: len(pages_by_star.get(key, [])) for key in list(star_labels.keys())},
        "language_counts": {key: len(pages_by_language.get(key, [])) for key in LANGUAGE_ORDER},
        "matrix_updated_stars_nonempty": len(pages_matrix),
        "matrix_updated_stars_language_nonempty": len(pages_matrix_language),
    }
    write_json(derived_root / "index.json", index)

    for key in updated_labels:
        rows = sorted(pages_by_updated.get(key, []), key=lambda item: item["repo_key"])
        payload = page_payload({"updated_bucket": key}, rows, generated_at)
        write_json(derived_root / "by-updated" / f"{key}.json", payload)
        write_text(markdown_root / "by-updated" / f"{slug_label(key)}.md", page_markdown(updated_labels[key], {"updated_bucket": key}, rows, generated_at))

    for key in star_labels:
        rows = sorted(pages_by_star.get(key, []), key=lambda item: item["repo_key"])
        payload = page_payload({"star_bucket": key}, rows, generated_at)
        write_json(derived_root / "by-stars" / f"{key}.json", payload)
        write_text(markdown_root / "by-stars" / f"{slug_label(key)}.md", page_markdown(star_labels[key], {"star_bucket": key}, rows, generated_at))

    for key in LANGUAGE_ORDER:
        rows = sorted(pages_by_language.get(key, []), key=lambda item: item["repo_key"])
        payload = page_payload({"language_bucket": key}, rows, generated_at)
        write_json(derived_root / "by-language" / f"{key}.json", payload)
        write_text(markdown_root / "by-language" / f"{slug_label(key)}.md", page_markdown(LANGUAGE_LABELS[key], {"language_bucket": key}, rows, generated_at))

    for updated_key, star_key in sorted(pages_matrix):
        rows = sorted(pages_matrix[(updated_key, star_key)], key=lambda item: item["repo_key"])
        payload = page_payload({"updated_bucket": updated_key, "star_bucket": star_key}, rows, generated_at)
        write_json(derived_root / "matrix-updated-stars" / updated_key / f"{star_key}.json", payload)
        title = f"{updated_labels[updated_key]} · {star_labels[star_key]}"
        write_text(markdown_root / "matrix-updated-stars" / slug_label(updated_key) / f"{slug_label(star_key)}.md", page_markdown(title, {"updated_bucket": updated_key, "star_bucket": star_key}, rows, generated_at, note="Static generated page. No frontend-only filtering or sorting is embedded in Markdown; use neighboring facet pages for traversal."))

    for updated_key, star_key, language_key in sorted(pages_matrix_language):
        rows = sorted(pages_matrix_language[(updated_key, star_key, language_key)], key=lambda item: item["repo_key"])
        payload = page_payload({"updated_bucket": updated_key, "star_bucket": star_key, "language_bucket": language_key}, rows, generated_at)
        write_json(derived_root / "matrix-updated-stars-language" / updated_key / star_key / f"{language_key}.json", payload)
        title = f"{updated_labels[updated_key]} · {star_labels[star_key]} · {LANGUAGE_LABELS[language_key]}"
        write_text(markdown_root / "matrix-updated-stars-language" / slug_label(updated_key) / slug_label(star_key) / f"{slug_label(language_key)}.md", page_markdown(title, {"updated_bucket": updated_key, "star_bucket": star_key, "language_bucket": language_key}, rows, generated_at, note="Static generated page. Sorting is precomputed in fixed sections below; there is no client-side Markdown-native filtering."))

    index_md = [
        "# Discovery pages",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "This index is static. It links to precomputed facet pages and does not rely on client-side filtering or sorting.",
        "",
        "## Counts",
        "",
        f"- repos: {index['repo_count']}",
        f"- non-empty updated × stars pages: {index['matrix_updated_stars_nonempty']}",
        f"- non-empty updated × stars × language pages: {index['matrix_updated_stars_language_nonempty']}",
        "",
        "## Updated buckets",
        "",
    ]
    for key in updated_labels:
        index_md.append(f"- [{updated_labels[key]}](./by-updated/{slug_label(key)}.md) — {index['updated_counts'][key]} repos")
    index_md += ["", "## Star buckets", ""]
    for key in star_labels:
        index_md.append(f"- [{star_labels[key]}](./by-stars/{slug_label(key)}.md) — {index['star_counts'][key]} repos")
    index_md += ["", "## Language buckets", ""]
    for key in LANGUAGE_ORDER:
        index_md.append(f"- [{LANGUAGE_LABELS[key]}](./by-language/{slug_label(key)}.md) — {index['language_counts'][key]} repos")
    write_text(markdown_root / "index.md", "\n".join(index_md) + "\n")

    summary = {
        "generated_at": generated_at,
        "repo_count": len(facts),
        "matrix_updated_stars_nonempty": len(pages_matrix),
        "matrix_updated_stars_language_nonempty": len(pages_matrix_language),
        "updated_counts": index["updated_counts"],
        "star_counts": index["star_counts"],
        "language_counts": index["language_counts"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def main():
    if len(sys.argv) != 2:
        print("usage: build_discovery_pages.py <data_root>", file=sys.stderr)
        raise SystemExit(1)
    data_root = Path(sys.argv[1])
    build_pages(data_root)


if __name__ == "__main__":
    main()
