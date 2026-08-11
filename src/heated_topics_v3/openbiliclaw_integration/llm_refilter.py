"""LLM-driven secondary filter for v2.1.x candidates.

After the embedding-similarity pre-filter, candidates that hit
``sim_threshold`` may still be off-persona — keyword-adjacent articles
that look related by string but actually cover a different niche. We use
the LLM (the same one already used for keyword extraction) to re-judge
each candidate in batches and drop the rejects.

Off by default. Enabled via ``--llm-refilter`` in the CLI or
``use_llm_refilter=True`` to ``run_one_user``. Per-batch failures fall
through to "keep the batch as-is" so a flaky LLM never silently strips
the entire candidate pool.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

DEFAULT_BATCH_SIZE = 10
DEFAULT_TIMEOUT = 60.0

# Strings the LLM may return that we recognise as truthy / falsy.
_TRUTHY = frozenset({"true", "yes", "1", "符合", "是", "y", "t"})
_FALSY = frozenset({"false", "no", "0", "不符合", "否", "n", "f"})


_SYSTEM_PROMPT = """你是中文内容运营专家。给定用户画像和一批候选文章的标题+摘要，判断每篇文章是否真正符合用户画像描述的内容方向。

只返回 JSON 数组，每篇文章一个布尔值（true=符合，false=不符合），顺序与输入一致。

判断标准：
- 文章主题是否落在用户画像描述的赛道 / 人设范围内？
- 文章角度是否对用户的创作方向有参考价值？
- 字面提到关键词但实际讲的是别的事（如评测、蹭流量的盘点）→ 判 false。
- 领域接近但用户画像明显不在该垂直方向 → 判 false。
- 文章信息太少无法判断时，倾向于 true（让后续 MMR 决定）。"""


_USER_PROMPT_TEMPLATE = """# 用户画像
- 赛道一：{track_1}
- 赛道二：{track_2}
- 人设：{persona}

# 候选文章（共 {n} 篇）
{candidates_block}

请输出恰好 {n} 个布尔值的 JSON 数组，true=符合，false=不符合。顺序与上面的 1..{n} 一一对应。"""


def _format_candidates(candidates: list[Any]) -> str:
    """Format candidates into a numbered list for the LLM prompt."""
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        title = (getattr(c, "title", "") or "").strip()
        summary = (getattr(c, "description", "") or "").strip()[:300]
        lines.append(f"{i}. 标题：{title}\n   摘要：{summary}")
    return "\n".join(lines)


def _parse_judgments(text: str, expected: int) -> list[bool] | None:
    """Extract a JSON list of booleans from LLM output.

    Accepts bare JSON, fenced ```json ... ```, and noisy prefixes/suffixes.
    Returns None when the response can't be coerced to ``expected`` booleans.
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = [ln for ln in stripped.splitlines() if not ln.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list) or len(data) != expected:
        return None
    out: list[bool] = []
    for item in data:
        if isinstance(item, bool):
            out.append(item)
        elif isinstance(item, str):
            v = item.strip().lower()
            if v in _TRUTHY:
                out.append(True)
            elif v in _FALSY:
                out.append(False)
            else:
                return None
        else:
            return None
    return out


async def refilter_candidates(
    candidates: list[Any],
    *,
    user_context: dict[str, str],
    llm_service: Any,
    batch_size: int = DEFAULT_BATCH_SIZE,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Any]:
    """Drop candidates that don't truly match the user's persona.

    Batches candidates (default 10 per LLM call) and asks the model to
    return a JSON array of booleans in input order. On any per-batch
    failure (exception, unparseable response, wrong length), keeps the
    batch unchanged and logs a warning — this never silently strips the
    whole pool.

    Returns the kept candidates in their original order.
    """
    if not candidates:
        return []
    if batch_size <= 0:
        batch_size = DEFAULT_BATCH_SIZE

    kept: list[Any] = []
    for start in range(0, len(candidates), batch_size):
        batch = candidates[start : start + batch_size]
        batch_n = len(batch)
        prompt = _USER_PROMPT_TEMPLATE.format(
            track_1=user_context.get("track_1", "") or "（无）",
            track_2=user_context.get("track_2", "") or "（无）",
            persona=user_context.get("persona", "") or "（无）",
            n=batch_n,
            candidates_block=_format_candidates(batch),
        )
        try:
            response = await asyncio.wait_for(
                llm_service.complete_with_core_memory(
                    system_instruction=_SYSTEM_PROMPT,
                    user_input=prompt,
                    json_mode=True,
                    temperature=0.2,
                    max_tokens=512,
                    caller="integration.llm_refilter",
                    inject_core_memory=False,
                ),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning(
                "LLM refilter batch %d..%d failed (%s); keeping batch as-is",
                start, start + batch_n, exc,
            )
            kept.extend(batch)
            continue

        judgments = _parse_judgments(response.content or "", batch_n)
        if judgments is None:
            logger.warning(
                "LLM refilter returned unparseable response for batch "
                "%d..%d; keeping batch as-is. raw=%r",
                start, start + batch_n, (response.content or "")[:200],
            )
            kept.extend(batch)
            continue

        for cand, keep in zip(batch, judgments):
            if keep:
                kept.append(cand)
            else:
                logger.debug(
                    "LLM refilter dropped: %s",
                    getattr(cand, "title", ""),
                )

    logger.info(
        "LLM refilter: kept %d / %d candidates",
        len(kept), len(candidates),
    )
    return kept