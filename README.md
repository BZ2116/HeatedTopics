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
