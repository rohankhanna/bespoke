# Discovery Facet Matrix And Page Generation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add a GitHub-native facet-generation job that produces deterministic page/artifact slices over discovered repositories using non-overlapping freshness, star, language, and product-surface buckets.

**Architecture:** Keep discovery and page generation separate. Discovery continues to collect raw GitHub-native repo records, concept observations, concepts, components, and indexes on `data`. A later deterministic aggregation step reads those artifacts and emits facet pages/indexes for browsing and downstream selection without introducing scraping or score-based ranking.

**Tech Stack:** Python 3.11 standard library, existing `scripts/github_seed_discovery.py` outputs, deterministic JSON artifacts on `data`, GitHub Actions for bounded scheduled/manual runs.

---

## Recommended facet schema

### Primary axes

1. `updated_bucket`
2. `star_bucket`
3. `language_bucket`

These are the first matrix pages because they are:
- GitHub-native
- mechanically derivable
- stable enough for deterministic bucket assignment
- useful for diversifying ecosystem slices without introducing ranking/scoring

### Secondary axes

These should be added after the primary matrix is stable.

4. `product_surface_bucket`
- inferred from repo description, manifests, workflows, components, and concepts
- examples: `cli`, `library`, `framework`, `service-api`, `web-app`, `infra-tooling`, `template-starter`, `docs-knowledge`, `model-or-data`

5. `toolchain_presence`
- derived booleans / small sets such as:
  - `has_github_actions`
  - `has_docker`
  - `has_pyproject`
  - `has_package_json`
  - `has_cargo_toml`
  - `has_makefile`
  - `has_devcontainer`

6. `concept_bucket`
- derived from symbolic layer, not only raw GitHub topics
- examples: `agent-framework`, `evaluation`, `retrieval`, `memory`, `orchestration`, `model-serving`, `observability`, `cli-tooling`, `infra`, `ui`, `data-processing`

### Filter-only dimensions

These are useful as filters/facets but not necessarily as first-class page matrices.

- `is_fork`
- `is_archived`
- `license_bucket`
- `documentation_richness`
- `owner_type`

---

## Exact bucket definitions

### Updated buckets

Use non-overlapping buckets based on `pushed_at` from GitHub repo metadata.

- `updated_0_1d` = updated in the last 24 hours
- `updated_1_7d` = 1 to 7 days old
- `updated_8_14d` = 8 to 14 days old
- `updated_15_30d` = 15 to 30 days old
- `updated_31_60d` = 31 to 60 days old
- `updated_61_90d` = 61 to 90 days old
- `updated_91_180d` = 91 to 180 days old
- `updated_181d_plus` = older than 180 days

Keep labels machine-first in artifacts and map to friendlier display text separately.

### Star buckets

Use non-overlapping buckets based on `stargazers_count`.

- `stars_0`
- `stars_1_9`
- `stars_10_99`
- `stars_100_999`
- `stars_1000_9999`
- `stars_10000_99999`
- `stars_100000_999999`
- `stars_1000000_plus`

### Language buckets

Use GitHub primary language first. Keep a catch-all bucket for everything else.

- `python`
- `typescript`
- `javascript`
- `go`
- `rust`
- `java`
- `c_cpp`
- `shell`
- `other`
- `unknown`

Implementation note:
- normalize `C`, `C++`, `Objective-C`, and related close relatives into `c_cpp` only if desired for matrix compactness
- otherwise split later if bucket sizes justify it

### Product-surface buckets

Do not treat these as GitHub-native truth. Treat them as deterministic derived slices from existing symbolic and component evidence.

Start with:
- `cli`
- `library`
- `framework`
- `service_api`
- `web_app`
- `infra_tooling`
- `template_starter`
- `docs_knowledge`
- `model_or_data`
- `unknown`

---

## Page-generation artifact design

### Core output directory

Write derived page artifacts under:

- `data/derived/discovery-pages/`

Recommended structure:

- `data/derived/discovery-pages/index.json`
- `data/derived/discovery-pages/by-updated/<updated_bucket>.json`
- `data/derived/discovery-pages/by-stars/<star_bucket>.json`
- `data/derived/discovery-pages/by-language/<language_bucket>.json`
- `data/derived/discovery-pages/matrix-updated-stars/<updated_bucket>/<star_bucket>.json`
- `data/derived/discovery-pages/matrix-updated-stars-language/<updated_bucket>/<star_bucket>/<language_bucket>.json`

### Page artifact shape

Each page artifact should include:

```json
{
  "generated_at": "ISO-8601",
  "facet_version": 1,
  "filters": {
    "updated_bucket": "updated_1_7d",
    "star_bucket": "stars_100_999",
    "language_bucket": "python"
  },
  "counts": {
    "repos": 123,
    "concepts": 456,
    "observations": 789,
    "components": 321,
    "terms": 654
  },
  "repo_ids": [
    "owner/repo"
  ]
}
```

Keep page artifacts as index-like outputs, not duplicated full repo documents.

### Companion indexes

Also emit:

- `data/derived/discovery-pages/repo-facets.jsonl`

Each line should hold one repo plus its assigned buckets. Example:

```json
{
  "repo": "owner/repo",
  "updated_bucket": "updated_1_7d",
  "star_bucket": "stars_100_999",
  "language_bucket": "python",
  "product_surface_bucket": "cli",
  "is_archived": false,
  "is_fork": false
}
```

This becomes the canonical intermediate for page generation.

---

## Job design

### Principle

Do not make the discovery job also perform arbitrary large fan-out page generation inline if that meaningfully harms discovery throughput. Prefer:

1. discovery job writes repo records and symbolic artifacts
2. page-generation step reads those deterministic artifacts and emits derived pages

### Recommended first implementation

Add a new deterministic Python script, for example:

- `scripts/build_discovery_pages.py`

Inputs:
- `data/discovery/repos/*.json`
- `data/discovery/concepts/*.json`
- `data/discovery/concept-observations/*.json`
- `data/discovery/components/*.json`
- `data/discovery/terms/*.json`

Outputs:
- `data/derived/discovery-pages/...`

### Scheduling options

Option A: run page generation at the end of each discovery job
- simplest
- guarantees pages stay current with each discovery commit
- acceptable if page build remains cheap

Option B: separate workflow/job
- better if page generation grows expensive
- can be triggered after discovery success or run on a separate manual/scheduled path

Recommended starting point:
- do Option A first
- split later only if it becomes materially expensive

---

## Deterministic bucket rules

### Repo inclusion rule

Only generate page entries for repos that already exist under:
- `data/discovery/repos/*.json`

Do not query GitHub again during page generation.

### Updated bucket rule

Use the repo record's GitHub-native timestamp field (`pushed_at` or equivalent preserved metadata).

### Star bucket rule

Use the repo record's `stargazers_count`.

### Language bucket rule

Use the repo record's `language` field if present.
Normalize to lowercase stable bucket keys.

### Product-surface rule

Infer deterministically from already collected evidence, in priority order:
1. manifests and components
2. workflow/toolchain evidence
3. description / README-derived symbolic concepts
4. fallback to `unknown`

Keep this rule table explicit in code and version it.

---

## Immediate implementation order

### Task 1: Add facet bucket helper functions

**Objective:** Create deterministic bucket helpers for updated time, stars, and language.

**Files:**
- Modify: `scripts/github_seed_discovery.py` or create `scripts/build_discovery_pages.py`
- Test: local script invocation against current `origin/data`

Deliver:
- `updated_bucket_for_repo(repo_record)`
- `star_bucket_for_repo(repo_record)`
- `language_bucket_for_repo(repo_record)`

### Task 2: Emit per-repo facet assignments

**Objective:** Build `repo-facets.jsonl` from existing repo records.

**Files:**
- Create: `scripts/build_discovery_pages.py`
- Output: `data/derived/discovery-pages/repo-facets.jsonl`

Deliver:
- one line per repo
- deterministic sorting by canonical repo identity

### Task 3: Emit first-level pages

**Objective:** Generate page indexes by each primary axis.

**Files:**
- Output:
  - `data/derived/discovery-pages/by-updated/*.json`
  - `data/derived/discovery-pages/by-stars/*.json`
  - `data/derived/discovery-pages/by-language/*.json`

Deliver:
- counts
- repo_ids
- filters

### Task 4: Emit first matrix pages

**Objective:** Generate `updated × stars` pages.

**Files:**
- Output: `data/derived/discovery-pages/matrix-updated-stars/...`

Deliver:
- all non-empty combinations
- skip empty pages unless an explicit placeholder index is desired

### Task 5: Emit second matrix pages

**Objective:** Generate `updated × stars × language` pages.

**Files:**
- Output: `data/derived/discovery-pages/matrix-updated-stars-language/...`

Deliver:
- only non-empty combinations
- keep file layout deterministic

### Task 6: Add run-summary observability for generated pages

**Objective:** Make page build visible in run summaries.

**Files:**
- Modify: page-generation script and/or discovery summary generation

Recommended summary fields:
- `page_repo_count`
- `page_counts_by_updated_bucket`
- `page_counts_by_star_bucket`
- `page_counts_by_language_bucket`
- `matrix_page_count`

### Task 7: Add product-surface bucket later

**Objective:** Add a derived `product_surface_bucket` once primary axes are stable.

Do not block the primary matrix on this.

---

## Verification plan

### Local verification

Run against current data branch contents in a temp worktree or exported tree.

Expected checks:
- all repos get exactly one updated bucket
- all repos get exactly one star bucket
- all repos get exactly one language bucket
- sum of repo_ids across each axis matches total repo count
- matrix pages contain only repos whose per-repo facet assignments match the page filters
- outputs are deterministic across repeated runs with unchanged input

### CI verification

Add a lightweight verification step:
- build pages
- rerun build
- assert no diff on second pass

### Useful audit outputs

Print or record:
- total repos assigned
- bucket counts by axis
- number of non-empty matrix pages
- top largest pages
- count of `unknown` language bucket

---

## Design constraints to preserve

- no web scraping
- no repo scoring/ranking during discovery
- no hardcoded allowlists/banlists for discovery scope
- keep page generation deterministic and derived from already-collected data
- keep symbolic truth separate from browsing/index artifacts
- treat product-surface and concept buckets as derived labels, not canonical truth

---

## Recommended next command-surface outcome

After implementation, the system should be able to answer questions like:
- show repos updated in the last week with 100 to 999 stars
- show Python repos updated in the last month with 10 to 99 stars
- show CLI-like repos in the last two weeks with 0 stars

without re-querying GitHub at browse time.
