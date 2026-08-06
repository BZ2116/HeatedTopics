# HeatedTopics V1

HeatedTopics V1 anonymously collects the official Toutiao and Juejin hot lists,
then generates a deterministic daily recommendation report from one saved
`primary_keyword`. V1 does not load `.env`, send a Cookie, or require an API key
or other credentials.

## Quick start

Install the project and collect the current public boards into `data/`:

```powershell
uv sync
uv run heated-topics collect-v1 --data-root data
```

Create a UTF-8 JSON profile using the fields shown in
`config/profiles/tech_ai_creator.json`, then generate the result twice to observe
same-business-day cache reuse:

`user_id` is a single filesystem-safe identifier: 1-64 ASCII letters, digits,
underscores, or hyphens, beginning with a letter or digit.

```powershell
uv run heated-topics generate-v1 --data-root data --profile config/profiles/tech_ai_creator.json
uv run heated-topics generate-v1 --data-root data --profile config/profiles/tech_ai_creator.json
```

Each workflow execution writes exactly one JSON status object to stdout. Collection reports
per-platform item counts. Generation returns `generated` or `no_result` on its
first completed run and `existing` when that user/business-date result is already
cached. Invalid arguments and failures return a nonzero exit code with a
sanitized JSON error.

## Output layout

```text
data/
|-- daily_hot_lists/<date>/
|   |-- raw/toutiao.json
|   |-- raw/juejin.json
|   |-- normalized/toutiao.json
|   |-- normalized/juejin.json
|   |-- details/toutiao_<sequence>.txt
|   |-- details/juejin_<sequence>.txt
|   `-- collection_status.json
`-- user_results/<user_id>/<business-date>/
    |-- report.md
    |-- result.json
    `-- topics/<platform>_<sequence>.txt
```

Toutiao is displayed before Juejin. V1 does not include a scheduler, frontend,
LLM ranking, or any other platform.

## Cached News Workflow

In addition to the V1 two-platform workflow, this branch ships an anonymous
three-platform cached news pipeline (Sina News, The Paper, NetEase News). The
news workflow never sends a Cookie, an Authorization header, an API key, or any
`.env` value.

```powershell
uv run heated-topics collect-news --data-root data
uv run heated-topics generate-news --data-root data --profile config/profiles/tech_ai_creator.json
```

The news workflow produces a distinct `news_user_results/` tree and never writes
into the V1 `user_results/` tree, so V1 and news results can coexist on the same
business date.

### Data layout for the news workflow

```text
data/
|-- daily_hot_lists/<date>/
|   |-- raw/<platform>.<suffix>      # captured once per day per platform
|   |-- normalized/<platform>.json   # validated official-board records
|   |-- eligible/<platform>.json     # only full_text + verified heat evidence
|   |-- rejected/<platform>.json     # reasons for each rejected record
|   |-- details/<platform>_<item_id>.txt
|   `-- collection_status.json
|-- active_snapshots/<platform>.json # atomic eligible pointer per platform
|-- search_cache/<date>/<platform>/<sha256(keyword)>/
|   `-- status.json                  # success/empty/failed cache per keyword
`-- news_user_results/<user_id>/<business-date>/
    |-- report.md
    |-- result.json
    `-- topics/<platform>_<sequence>.txt
```

### Result limits and guarantees

* Each of `sina_news`, `thepaper`, `netease_news`, `zhihu_hot`, and
  `zhihu_daily` returns at most `MAX_RESULTS = 20` articles per user request.
* `zhihu_daily` heat evidence is rank-only official archive data
  (`platform_rank`, eight-digit `recommendation_date`), with empty metrics.
  Search is bounded to a seven-day archive scan that caches up to 60 unique
  type-0 stories per `(keyword, collected_at date)`; later pages slice the
  cache without new HTTP calls.
* Both providers are anonymous and cookie-free: no `.env`, Cookie, header, or
  credential is read, sent, or persisted.
* Formal results are constructed only from `QualifiedArticle` records whose
  detail `content_status` is `full_text` and whose heat evidence contains a
  non-empty `qualified_by` set; `summary` and `title_only` records never become
  formal recommendations.
* Search is skipped when a platform already has at least `MIN_RESULTS = 5`
  matched cached records; otherwise the search runs in pages of
  `SEARCH_PAGE_SIZE = 15` and stops at most `MAX_SEARCH_CANDIDATES = 60` unique
  candidates or `MAX_RESULTS = 20` qualified records.
* The active eligible snapshot is only reused when it is at most 48 hours old,
  otherwise the cached board is treated as missing.

### Deferred

Tencent News is intentionally deferred for this batch because no confirmed
anonymous keyword search endpoint is currently available.

`baidu_hot` is temporarily removed from `NEWS_PLATFORMS` because every hot
board event links to a Baidu search-result page rather than a real article
URL, and the `s?wd=` fallback path is currently blocked by Baidu's captcha
wall. The `BaiduHotProvider` source file remains in `providers/baidu_hot.py`
and its unit tests in `tests/providers/test_baidu_hot.py` are kept so the
provider can be re-registered once a non-captcha search path is wired in.

### Zhihu sources

`zhihu_daily` is anonymous. `zhihu_hot` needs a locally maintained
`ZHIHU_COOKIE` in `.env`.

Check it without writing the Cookie or response body:

```powershell
uv run heated-topics check-zhihu-auth
```

Valid output:

```json
{"status":"valid","command":"check-zhihu-auth","checked_at":"2026-07-25T20:00:00+08:00"}
```

If the status is `missing` or `expired`, replace only the local `.env` value
and rerun the check. `collect-news` isolates this failure from every other
platform.

---

## Multi-user OpenBiliClaw recommender

This pipeline reads lightweight user profiles from Excel, obtains candidates from
V3 hot lists and/or last30days, lets OpenBiliClaw rank them, and writes an
isolated report directory for each user.

### What you get

Each user report contains:

- `input.json` — user profile plus an article index with query provenance, heat,
  publication time, and a pointer to the body file
- `summary.txt` — one Chinese brief covering all queries for that user
- `text/NN.txt` — one complete article body per recommendation, named by the
  two-digit recommendation rank

Article bodies are not duplicated in JSON. Failures are isolated per user, so
one user failing does not stop the remaining users.

### Prerequisites

| Component | Why | How |
|---|---|---|
| Python 3.11+ | project | `uv sync` or `pip install -e .` |
| `OPENBILICLAW_LLM_API_KEY` env var | LLM call (MiniMax-M2.7 via `https://api.minimaxi.com/v1`) | export before running the CLI |
| Ollama running on `http://127.0.0.1:11434` with `bge-m3` pulled | embedding service for MMR | `ollama pull bge-m3` |
| OpenBiliClaw patched with `serve_external_candidates` | the engine entry point this CLI calls | see *Patching OpenBiliClaw* below |

### One-time setup

```bash
# 1. Install the patched OpenBiliClaw into your venv
git clone https://github.com/whiteguo233/OpenBiliClaw.git openbiliclaw-sandbox
# apply the serve_external_candidates patch (see openbiliclaw-sandbox/PATCH_NOTES.md),
# then:
pip install -e openbiliclaw-sandbox

# 2. Copy the example config
cp config/openbiliclaw.toml.example config/openbiliclaw.toml

# 3. Export the API key
export OPENBILICLAW_LLM_API_KEY=sk-...

# 4. (Optional) point at a shared DailyHotApi cache
export DAILYHOT_CACHE_DIR=/path/to/data/cache/dailyhot
```

### Running

```bash
source .venv/Scripts/activate
export PYTHONPATH=src
export OPENBILICLAW_LLM_API_KEY=sk-...

python -m heated_topics_v3.openbiliclaw_integration.cli \
    --users-excel users.xlsx \
    --output-dir data/run_20260806 \
    --source both \
    --last30days-cli-path "E:/.code/My/last30days-skill-cn/scripts/last30days.py" \
    --limit 8 \
    --max-parallel 5 \
    --per-user-timeout 300
```

| Flag | Default | Meaning |
|---|---|---|
| `--users-excel` | required | Excel input with `user_id`, `track_1`, `track_2`, and `persona` |
| `--output-dir` | required | per-run root containing `inputs/` and `outputs/` |
| `--limit` | `8` | top-N recommendations per user |
| `--source` | `both` | `v3-hotlist`, `last30days`, or both |
| `--last30days-cli-path` | none | required when source includes last30days |
| `--last30days-max-queries` | `3` | maximum last30days queries per user |
| `--max-parallel` | `5` | concurrent users; `1` runs serially |
| `--per-user-timeout` | `300` | timeout in seconds for one user |
| `--body-max-chars` | `50000` | maximum characters written to each body file |
| `--no-keyword-extraction` | off | use `track_1`/`track_2` directly instead of LLM keywords |
| `--min-view-count` | `0` | minimum candidate view count; zero disables the filter |
| `--heat-source` | `rank` | use source rank or view count as the heat factor |
| `--llm-refilter` | off | enable a post-embedding LLM relevance filter |

### Excel input

The first worksheet must contain these four columns. Header matching is
case-insensitive and accepts the listed Chinese aliases.

| Field | Accepted aliases | Meaning |
|---|---|---|
| `user_id` | `用户ID`, `用户编号` | caller-supplied output key |
| `track_1` | `第一赛道`, `赛道一` | primary content track |
| `track_2` | `第二赛道`, `赛道二` | secondary content track |
| `persona` | `人设`, `画像` | creator persona |

Blank rows are skipped. Missing or empty required fields fail validation before
any user is processed.

For the desktop three-column workbook, `data/run_20260804/run_desktop_all.py`
derives a stable ID from profile content:

```text
u_<sha256(track_1 + "\0" + track_2 + "\0" + persona)[:8]>
```

This ID remains stable when Excel row order changes.

### `config/openbiliclaw.toml`

```toml
[llm]
routing_version = 2
default_chain   = ["minimax"]    # must match an [llm.instances.*] key

[llm.instances.minimax]
name           = "minimax"       # LOWERCASE — see warning in openbiliclaw.toml.example
provider_type  = "openai_compatible"
enabled        = true
model          = "MiniMax-M2.7"
base_url       = "https://api.minimaxi.com/v1"
# api_key is sourced from $OPENBILICLAW_LLM_API_KEY at runtime

[llm.embedding]
provider             = "ollama"
model                = "bge-m3"
output_dimensionality = 1024
```

If the file is missing, the CLI falls back to the same defaults from env. If `OPENBILICLAW_LLM_API_KEY` is unset, the CLI exits with code 2 before running anything.

### Output layout

The CLI writes one registry for the run and one directory per user. It does not
write a consolidated recommendation JSON file.

```text
<output-dir>/
├── inputs/
│   └── users.json
└── outputs/
    └── u_<user-id>/
        ├── input.json
        ├── summary.txt
        └── text/
            ├── 01.txt
            ├── 02.txt
            └── NN.txt
```

`inputs/users.json` maps each `user_id` to its three profile fields. A user
report's `input.json` contains the metadata and an `articles` array. Each article
entry includes `rank`, `title`, `url`, `platform`, `query`, `heat`,
`published_at`, and `body_file`; the complete body is only in that referenced
`text/NN.txt` file.

Example `input.json`:

```json
{
  "user_id": "u_001",
  "track_1": "AI 大模型",
  "track_2": "副业",
  "persona": "技术博主",
  "generated_at": "2026-08-06T12:34:56+08:00",
  "recommendation_count": 1,
  "summary_file": "summary.txt",
  "articles": [
    {
      "rank": 1,
      "title": "...",
      "url": "https://...",
      "platform": "weibo",
      "query": "大模型应用",
      "heat": {"view": 12345, "like": 678, "comment": 90, "favorite": 12, "share": 5, "rank": 1},
      "published_at": "",
      "body_file": "text/01.txt"
    }
  ]
}
```

`summary.txt` is one Chinese content brief covering the user's query groups;
it is not one file per query. Empty or failed summaries still produce an empty
`summary.txt`, while article bodies remain available independently.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All users produced recommendations |
| `1` | At least one user errored (`error` field present) — others may have succeeded |
| `2` | Bad CLI args, missing `OPENBILICLAW_LLM_API_KEY`, or invalid Excel input |
| `4` | Fatal error inside `run_all_users` or output write failed |
| `130` | SIGINT (Ctrl-C) |

### Tests

```bash
source .venv/Scripts/activate
export PYTHONPATH=src
python -m pytest tests/openbiliclaw_integration tests/providers -v
```

The openbiliclaw integration suite currently covers Excel validation, stable user
IDs, keyword extraction, candidate adaptation, source dispatch, concurrency,
overall summary generation, report writing, and end-to-end output isolation.

The provider suite covers every V3 provider including the DailyHotApi adapter (6 tests for cache-scan lookup, fetch_detail title-only / full-text / HTTP-failure paths).

### File layout

```text
src/heated_topics_v3/openbiliclaw_integration/
├── cli.py               # Excel input, orchestration, and per-user report writes
├── recommender.py       # candidate collection, ranking, and in-memory payloads
├── user_profile.py      # minimal UserSpec and stable profile hash IDs
├── keyword_extractor.py # LLM query extraction and cache
├── candidate_adapter.py # source records → OpenBiliClaw DiscoveredContent
├── per_query_summary.py # one overall brief across all query groups
├── report_writer.py     # input.json + summary.txt + text/NN.txt
├── runtime.py           # runtime construction and environment checks
└── exceptions.py        # integration error hierarchy
```

### Troubleshooting

- **`RuntimeError: OpenBiliClaw patch missing`**: reinstall the patched OpenBiliClaw build that provides `RecommendationEngine.serve_external_candidates`.
- **All users fail with `engine_error`**: verify that Ollama is running and the configured embedding model is available.
- **A user gets too few recommendations**: inspect `_keyword_cache/<user_id>/keyword_cache.json`; regenerate weak keywords or adjust `--min-view-count` and the embedding threshold deliberately.
- **last30days returns no candidates**: verify `--last30days-cli-path`, increase `--last30days-timeout`, and inspect `<output-dir>/last30days/`.
- **`summary.txt` is empty**: the summary LLM call failed or no recommendation had query provenance; article metadata and `text/NN.txt` bodies remain usable.
- **A body file is empty**: the upstream provider could not extract full text for that URL; check the corresponding article URL and source response.
