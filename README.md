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

A second pipeline on top of V3 hot-list providers: take a list of user profiles,
let OpenBiliClaw rank and personalize the candidates, write a per-user
top-N JSON. Lives at `src/heated_topics_v3/openbiliclaw_integration/`.

### What you get

For each user, a list of up to `--limit` recommendations with:

- `title`, `url`, `source_platform` — what to read
- `body_text_preview` — first 800 chars (configurable) of the article body, fetched via HTTP + GNE
- `topic_label`, `reason` — LLM-generated (MiniMax-M2.7) one-line topic + friend-style explanation tuned to the user's interests
- `confidence` — `1/rank` from the hot-list position, used by the engine's MMR diversifier
- `heat.*` — view / like / comment / favorite / share / rank pulled from each provider's native metrics

Failures are isolated per user: one user crashing does not affect the others; the failing user's entry has `error` + `error_detail` fields instead of `recommendations`.

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
source .venv/Scripts/activate        # Windows: adjust path
export PYTHONPATH=src
export OPENBILICLAW_LLM_API_KEY=sk-...

python -m heated_topics_v3.openbiliclaw_integration.cli \
    --users  config/profiles/users_demo.json \
    --output data/recommendations.json \
    --limit  5 \
    --providers dailyhot:36kr,juejin,toutiao \
    --data-dir data/runtime \
    --max-parallel 5 \
    --per-user-timeout 300
```

| Flag | Default | Meaning |
|---|---|---|
| `--users` | required | path to `users.json` (see schema below) |
| `--output` | required | where to write the recommendations envelope |
| `--limit` | `10` | top-N per user |
| `--providers` | all | comma-separated; supports `dailyhot:<route>` (e.g. `dailyhot:36kr`, `dailyhot:zhihu`) |
| `--max-parallel` | `5` | concurrent users; `1` = serial |
| `--per-user-timeout` | `180` | seconds before a single user is marked `error: timeout` |
| `--body-preview-chars` | `800` | truncation length of `body_text_preview` |
| `--config` | `config/openbiliclaw.toml` | OpenBiliClaw config (see below) |
| `--data-dir` | `data` | per-user state root; each user gets `data/users/<id>/openbiliclaw.db` |

### Available providers

| Name | Source |
|---|---|
| `juejin`, `toutiao`, `baidu_hot`, `zhihu_hot`, `zhihu_daily`, `sina_news`, `thepaper`, `netease_news` | first-party V3 providers (HTTP) |
| `dailyhot:<route>` | DailyHotApi cache reader — `route` is any of 40+ upstream platforms (`36kr`, `sspai`, `xiaohongshu`, `csdn`, `ithome`, `github`, `hellogithub`, `douyin`, `weibo`, `baidu`, `bilibili`, ...). Body is fetched per-URL via GNE with a `title_only` fallback. |

To list the routes currently in your cache:

```bash
python -c "import json,pathlib; p=pathlib.Path('data/cache/dailyhot'); \
  print(sorted({json.loads(f.read_text(encoding='utf-8')).get('key','').split(':')[1] \
  for f in p.iterdir() if f.suffix=='.json'}))"
```

### `users.json` schema

```json
{
  "users": [
    {
      "user_id": "caifu_001",
      "display_name": "普通人财富管理（学生/新人）",
      "interests": [
        {"name": "记账", "category": "理财", "weight": 0.85},
        {"name": "基金",  "category": "理财", "weight": 0.75}
      ],
      "disliked_topics": ["杠杆炒股", "一夜暴富"],
      "style": {"reading_depth": "medium", "tone_preference": "neutral"},
      "context": {"primary_scene": "general", "device": "mobile"},
      "exploration_openness": 0.4,
      "core_traits": ["稳扎稳打"],
      "deep_needs": ["可落地的实操内容"],
      "values": ["稳健", "不焦虑"],
      "life_stage": "大学 / 职场新人",
      "current_phase": "刚开始学理财",
      "cognitive_style": ["由表及里"],
      "recent_awareness": [{"date": "2026-07-29", "observation": "...", "trend": "...", "emotion_guess": "..."}],
      "active_insights":  [{"hypothesis": "...", "evidence": ["..."], "confidence": 0.7}],
      "favorite_up_users": [],
      "source_platform_mix": {}
    }
  ]
}
```

Required: `user_id`, `interests` (≥ 1, each with `name` and `weight ∈ [0, 1]`). Everything else is optional and gets a sensible default. See `tests/openbiliclaw_integration/fixtures/users_valid_3users.json` for three complete examples.

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

### Output envelope

```json
{
  "generated_at": "2026-07-30T20:30:00Z",
  "config_version": "0.3.186+mur.1",
  "llm_model": "MiniMax-M2.7",
  "embedding_model": "bge-m3",
  "users": [
    {
      "user_id": "caifu_001",
      "display_name": "...",
      "input_profile_summary": {"interests_count": 9, "disliked_count": 3},
      "pipeline": {
        "candidates_fetched": 50,
        "candidates_after_filter": 19,
        "candidates_considered_by_engine": 19,
        "embedding_degraded": false
      },
      "recommendations": [
        {
          "rank": 1,
          "title": "...",
          "url": "https://...",
          "source_platform": "dailyhot:36kr",
          "heat": {"view": 56641, "like": 0, "comment": 0, "favorite": 0, "share": 0, "rank": 1},
          "body_text_preview": "...",
          "body_text_length": 5336,
          "topic_label": "大厂投资思路里的稳健逻辑",
          "reason": "看了下腾讯这两年在AI上的投资版图...",
          "confidence": 1.0,
          "published_at": ""
        }
      ]
    },
    {
      "user_id": "u_broken",
      "error": "timeout",
      "error_detail": "exceeded 300s"
    }
  ]
}
```

The envelope is written atomically (`<output>.tmp` then `os.replace`) — a partial file is never observed by readers.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All users produced recommendations |
| `1` | At least one user errored (`error` field present) — others may have succeeded |
| `2` | Bad CLI args, missing `OPENBILICLAW_LLM_API_KEY`, or `users.json` invalid |
| `4` | Fatal error inside `run_all_users` or output write failed |
| `130` | SIGINT (Ctrl-C) |

### Tests

```bash
source .venv/Scripts/activate
export PYTHONPATH=src
python -m pytest tests/openbiliclaw_integration tests/providers -v
```

The openbiliclaw_integration suite (57 tests) covers: schema validation, profile building, candidate adapter (rank → relevance mapping), per-user error isolation, parallel orchestration, the `serve_external_candidates` patch verification, and config loading.

The provider suite covers every V3 provider including the DailyHotApi adapter (6 tests for cache-scan lookup, fetch_detail title-only / full-text / HTTP-failure paths).

### File layout

```text
src/heated_topics_v3/openbiliclaw_integration/
├── cli.py              # argparse entry; exit codes; atomic output write
├── recommender.py      # fetch_candidates → candidate_adapter → engine.serve_external_candidates
├── user_profile.py     # users.json schema + OnionProfile builder
├── candidate_adapter.py # V3 HotItem → openbiliclaw DiscoveredContent
├── output.py           # Recommendation → JSON dict + envelope builder
├── runtime.py          # config loader, env check, patch verification
└── exceptions.py       # IntegrationError hierarchy
```

### Troubleshooting

- **`RuntimeError: OpenBiliClaw patch missing`**: the `serve_external_candidates` method is not on `RecommendationEngine`. Re-install the patched openbiliclaw-sandbox (`pip install -e openbiliclaw-sandbox`) and rerun.
- **Every recommendation has `confidence: 0.0`**: the candidate adapter is not setting `relevance_score`. Confirm you're on a build that includes `src/heated_topics_v3/openbiliclaw_integration/candidate_adapter.py` (rank → `1/rank` mapping).
- **All users fail with `error: engine_error`**: usually the embedding service is unreachable. Check `curl http://127.0.0.1:11434/api/embeddings -d '{"model":"bge-m3","prompt":"test"}'`.
- **A `--providers dailyhot:<route>` returns zero items**: no cache file with `key="dailyhot:<route>:today"` exists in `data/cache/dailyhot` (or `$DAILYHOT_CACHE_DIR`). Run the upstream dailyhot client to refresh, or remove the route from `--providers`.
- **Body text is empty for an item**: GNE couldn't extract a usable body (`content_status: "title_only"`). The item still surfaces — the engine ranks by title — but personalization will be weaker.
