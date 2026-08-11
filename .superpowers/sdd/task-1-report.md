# Task 1 Report: Workflow Contracts

## Implementation

- Replaced the legacy profile/query/cluster contracts with frozen workflow dataclasses: `UserProfile`, `HeatMetrics`, `HotItem`, `ItemDetail`, `PlatformCollectionStatus`, `DailySnapshot`, `RecommendationItem`, and `RecommendationBundle`.
- Added the exact required `HeatLevel`, `FactStatus`, `ContentStatus`, and `GenerationStatus` literals, plus `CollectionStatus` for platform outcomes.
- Added the required recommendation sections and query metadata to `RecommendationBundle`.
- Configured Hatchling to install the `src/heated_topics_v3` package from the src layout. `uv.lock` was refreshed by `uv run`.

## Files

- `src/heated_topics_v3/contracts.py`
- `tests/test_contracts.py`
- `pyproject.toml`
- `uv.lock`

## RED

Command:

```text
uv run pytest tests/test_contracts.py -q
```

Initial output confirmed the authorized baseline packaging defect:

```text
ModuleNotFoundError: No module named 'heated_topics_v3'
1 error in 0.20s
```

After the minimal build configuration was added, the same command reached the contracts and failed for the intended missing API:

```text
ImportError: cannot import name 'ContentStatus' from 'heated_topics_v3.contracts'
1 error in 0.19s
```

## GREEN

Command:

```text
uv run pytest tests/test_contracts.py -q
```

Output:

```text
......                                                                   [100%]
6 passed in 0.04s
```

## Full Suite

The required full suite was run exactly once:

```text
uv run pytest -q
```

Result: collection stopped with one error because the legacy `src/heated_topics_v3/profile_queries.py` imports the removed `TopicQuery` contract. That module and its test are explicitly scheduled for replacement in Task 2.

```text
ImportError: cannot import name 'TopicQuery' from 'heated_topics_v3.contracts'
1 error in 0.23s
```

## Self-review

- Confirmed every required contract is frozen.
- Confirmed `HotItem` and `ItemDetail` contain every field named by the brief.
- Confirmed platform item collections are tuples and all three recommendation output sections are tuples.
- Confirmed the four specified literal aliases exactly match the brief.
- Confirmed packaging uses the smallest conventional Hatchling src-layout declaration and `git diff --check` passes.
- No credentials, provider behavior, or unrelated application logic were introduced.

## Concerns

- The full suite is not green until Task 2 replaces the intentionally obsolete `profile_queries.py` and its legacy test. Restoring `TopicQuery` or the old `UserProfile` schema here would contradict the replacement requirement.
