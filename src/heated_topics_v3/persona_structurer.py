"""Persona structurer.

Given raw persona data (level1, level2, persona_text), produce a
`PersonaPersonal` via the project's LM (`call_llm` from
`heated_topics_v3.llm_client`). A heuristic splitter is provided as a
private fallback; the public function does NOT auto-fall-back — callers
decide whether to fall back on `LLMUnavailable` / `PersonaStructureError`.

Why no built-in fallback: keeping the LLM path pure makes it trivial to
unit-test with a fake `llm=` callable, and the script entry point can log
the failure mode (LLM down vs. parse broken) instead of silently masking it.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable

from heated_topics_v3.contracts import PersonaPersonal
from heated_topics_v3.llm_client import call_llm, strip_code_fence


SYSTEM_PROMPT = """你是中文 persona 数据整理助手。给定人设原始数据，输出仅含以下四字段的 JSON，不要 Markdown 代码块、不要解释：

  role       - 用户身份/视角定位，名词短语，不带动词，可含履历/经验/资格。
  subject    - 用户生产内容的题材（核心创作对象），可以是动宾短语但要去掉
               "专注/专门/主打/用X讲/把X讲成Y" 等表演性动词头，留下研究对象。
  scenarios  - subject 下的 3-6 个细分场景/选题关键词，2-6 字为主的名词短语，
               去重，去掉"不X"等否定前缀。
  value      - 用户对读者的差异化价值主张，一句话，含 audience 线索更好。

严格只输出 JSON 对象，键名固定为 role / subject / scenarios / value。
"""


class PersonaStructureError(ValueError):
    """Raised when the LM response cannot be parsed into a valid PersonaPersonal."""


_REQUIRED_FIELDS: tuple[str, ...] = ("role", "subject", "scenarios", "value")


def structure_persona(
    level1: str,
    level2: str,
    persona_text: str,
    *,
    llm: Callable[..., str] | None = None,
    use_cache: bool = True,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> PersonaPersonal:
    """Return a PersonaPersonal built by the LM from raw persona fields.

    On parse failure or missing fields, raises `PersonaStructureError`.
    Callers should catch `LLMUnavailable` separately (network / config).
    """
    payload = {
        "level1": level1,
        "level2": level2,
        "persona_text": persona_text.strip(),
    }
    prompt = (
        "请整理以下 persona 数据：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    caller = llm or call_llm
    raw = caller(
        prompt,
        system=SYSTEM_PROMPT,
        use_cache=use_cache,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _parse_response(raw)


def _parse_response(raw_text: str) -> PersonaPersonal:
    cleaned = strip_code_fence(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise PersonaStructureError(f"LM response is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PersonaStructureError(
            f"LM response root must be an object, got {type(data).__name__}"
        )
    missing = [k for k in _REQUIRED_FIELDS if k not in data]
    if missing:
        raise PersonaStructureError(f"LM response missing fields: {', '.join(missing)}")

    role = str(data["role"]).strip()
    subject = str(data["subject"]).strip()
    value = str(data["value"]).strip()
    if not role or not subject or not value:
        raise PersonaStructureError(
            "LM response fields role/subject/value must be non-empty"
        )
    scenarios_raw = data["scenarios"]
    if not isinstance(scenarios_raw, list):
        raise PersonaStructureError(
            f"scenarios must be a list, got {type(scenarios_raw).__name__}"
        )
    scenarios: list[str] = []
    seen: set[str] = set()
    for entry in scenarios_raw:
        s = str(entry).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        scenarios.append(s)
    if not scenarios:
        raise PersonaStructureError("scenarios parsed to empty list")
    if len(scenarios) > 6:
        scenarios = scenarios[:6]

    return PersonaPersonal(
        role=role,
        subject=subject,
        scenarios=tuple(scenarios),
        value=value,
    )


# ---------------------------------------------------------------------------
# Heuristic fallback (no LLM). Used by the build script when the LM is
# unavailable, the caller asked for it, or unit tests want deterministic input.
# ---------------------------------------------------------------------------

_VERB_LEAD_RE = re.compile(
    r"^(?:专注|专门|主打|着重|分享)?"
    r"(?:拆解|分享|记录|研究|观察|讲述|讲解|拆|讲)?"
    r"(?:用[一-鿿A-Za-z0-9 ]{1,8}(?:讲|聊|拆|写|分析))?"
    r"(?:把[一-鿿A-Za-z0-9 ]{1,8}(?:讲|聊|拆|写|分析)成?)?"
    r"(?:把[一-鿿A-Za-z0-9 ]{1,4})?"
    r"(?:的)?"
)

_BA_STRUCTURE_RE = re.compile(
    r"^(?:专门|专注|主打|着重|分享|用[一-鿿A-Za-z0-9 ]{0,8})?"
    r"把(.{1,60}?)(?:讲|聊|拆|写|分析)成?(.*)$"
)
_BU_PREFIX_RE = re.compile(r"^不[一-鿿A-Za-z0-9]{1,8}$")


def _strip_verb_lead(part: str) -> str:
    candidate = part
    for _ in range(5):
        new = _VERB_LEAD_RE.sub("", candidate, count=1).strip()
        if new == candidate:
            break
        candidate = new
    return candidate


def _strip_ba_structure(part: str) -> str:
    """If part contains '把 X 讲/拆成 Y', keep X and drop the scaffolding.

    Y is returned in `value_via_ba` via the second return slot — but for the
    pure scenario-stripping path we just need X; value integration happens
    inside `_chunks_subject_value`.
    """
    match = _BA_STRUCTURE_RE.match(part)
    if match:
        return match.group(1).strip(" ，。的")
    return part


def _chunks_subject_value(chunks: list[str]) -> tuple[str, str, list[str]]:
    """From a list of comma-separated chunks, return (subject, value, scenarios).

    Last chunk = value; leading chunks form subject. Chunks matching ^不X$
    are anti-claims — they leave the subject and prepend to value. scenarios
    are subject fragments split on 、or 和 after sweeping whole-subject
    "把X讲成Y" scaffolding and per-fragment verb leads.
    """
    if not chunks:
        return "", "", []
    if len(chunks) == 1:
        return "", chunks[0], []

    value = chunks[-1]
    lead = chunks[:-1]
    subject_pieces: list[str] = []
    for raw in lead:
        clean = raw.strip()
        if _BU_PREFIX_RE.match(clean):
            value = f"{clean}，{value}" if value != clean else value
            continue
        subject_pieces.append(clean)
    subject = "，".join(subject_pieces) or chunks[0]

    # Subject-level sweep: collapse "专门把X讲成Y" patterns to just X so the
    # X noun list survives into the scenario extraction step. The Y part is
    # merged into value (it carries the user's editorial angle).
    ba_whole = _BA_STRUCTURE_RE.match(subject)
    if ba_whole:
        subject = ba_whole.group(1).strip(" ，。的")
        y_part = ba_whole.group(2).strip(" ，。")
        if y_part and y_part not in value:
            value = f"{y_part}，{value}"

    scenarios: list[str] = []
    for raw in re.split(r"[、，和与]", subject):
        clean = raw.strip(" 。,")
        # Per-fragment: also try stripping "把X讲成Y" if present.
        ba = _BA_STRUCTURE_RE.match(clean)
        if ba:
            clean = ba.group(1).strip(" ，。的")
        clean = _strip_verb_lead(clean)
        if 2 <= len(clean) <= 8 and not _BU_PREFIX_RE.match(clean):
            if clean not in scenarios:
                scenarios.append(clean)
        if len(scenarios) >= 6:
            break
    return subject, value, scenarios


# ---------------------------------------------------------------------------
# No-LLM keyword extraction (level1/level2 first, persona nouns as supplement).
# Same heuristic family as `_split_heuristic` but tuned for short search terms.
# ---------------------------------------------------------------------------

_LEAD_VERB_RE = re.compile(
    r"^(?:专注|专门|主打|着重|用|把|记录|研究|观察|关注|追踪|分享|讲解|讲述|讲清|解读|测试|拆解|聊|讲|拆|清|解|写|分析)"
)
_MID_STOP_RE = re.compile(
    r"(?:只用|不[一-鿿]|面向|从|只|把|爱|喜欢|专为)"
)
_TRAIL_VERB_RE = re.compile(r"(?:切入|拆解|分享|解读|研究|讲|聊|拆|写|分析)$")
_BAD_TOKEN_RE = re.compile(
    r"^(?:普通|小白|新人|专门|专注|主打|着重|分享|记录|的人|我们|你|我|的)$"
)
_LEVEL_TAIL_RE = re.compile(
    r"(?:解读|分析|应用|管理|研究|观察|分享|故事|拆解|评测|追踪|记录)$"
)


def _drop_level_tail(value: str) -> str:
    cleaned = _LEVEL_TAIL_RE.sub("", value).strip()
    return cleaned or value


def _clean_chunk(s: str) -> str:
    s = s.strip(" 。,的")
    for _ in range(3):
        new = _LEAD_VERB_RE.sub("", s, count=1).strip(" 。,的")
        new = _MID_STOP_RE.sub("", new, count=1).strip(" 。,的")
        if new == s:
            break
        s = new
    s = _TRAIL_VERB_RE.sub("", s).strip(" 。,的")
    return s


def _extract_noun_chunks(persona_text: str) -> list[str]:
    """Pull short noun-ish phrases out of persona_text.

    Splits on Chinese particles (、，和与) and Chinese full stops (。). After
    stripping leading/trailing performing verbs and obvious stopwords, any
    remaining 2-5 char fragment is kept.

    Chunks starting with `不` are dropped wholesale: the negation prefix in
    `不X` flips the polarity of X (e.g. `不讲暴富故事` → `暴富故事` would match
    get-rich content, opposite of the persona's intent).
    """
    seen: set[str] = set()
    out: list[str] = []
    text = persona_text.strip().rstrip("。").strip()
    for sent in text.split("。"):
        sent = sent.strip()
        if not sent:
            continue
        for raw in re.split(r"[、，和与]", sent):
            raw = raw.strip(" 。,的")
            if not raw or raw.startswith("不"):
                continue
            chunk = _clean_chunk(raw)
            if not chunk:
                continue
            for piece in re.split(r"[、，和与]", chunk):
                piece = piece.strip(" 。,的")
                if (
                    2 <= len(piece) <= 5
                    and piece not in seen
                    and not _BAD_TOKEN_RE.match(piece)
                ):
                    seen.add(piece)
                    out.append(piece)
    return out


def extract_short_keywords(
    level1: str,
    level2: str,
    persona_text: str,
    *,
    max_keywords: int = 5,
) -> tuple[str, ...]:
    """Build a persona keyword set without calling the LLM.

    Anchors are level1 and level2 (after dropping generic tails like
    解读/分析). Remaining slots are filled with noun phrases pulled from
    `persona_text`; when persona_text yields too few, the list is left short.
    """
    l1n = _drop_level_tail(level1.strip())
    l2n = _drop_level_tail(level2.strip())

    primary: list[str] = []
    if l1n:
        primary.append(l1n)
    if l2n and l2n != l1n:
        primary.append(l2n)

    nouns = _extract_noun_chunks(persona_text)
    seen = set(primary) | {level1, level2}
    extras: list[str] = []
    for noun in nouns:
        if noun not in seen:
            seen.add(noun)
            extras.append(noun)

    merged = primary + extras[: max(0, max_keywords - len(primary))]
    return tuple(merged[:max_keywords])


def _split_heuristic(text: str) -> tuple[str, str, list[str], str]:
    """Heuristic equivalent of `structure_persona`.

    Returns (role, subject, scenarios, value).
    """
    text = text.strip().rstrip("。").strip()
    if not text:
        return "", "", [], ""

    sentences = [s.strip() for s in text.split("。") if s.strip()]

    if len(sentences) == 1:
        chunks = [c.strip() for c in sentences[0].split("，") if c.strip()]
        if not chunks:
            return "", "", [], ""
        role = chunks[0]
        subject, value, scenarios = _chunks_subject_value(chunks[1:])
        return role, subject, scenarios, value

    role = sentences[0]
    body = sentences[1:]
    if len(body) == 1:
        chunks = [c.strip() for c in body[0].split("，") if c.strip()]
        if not chunks:
            return role, "", [], ""
        subject, value, scenarios = _chunks_subject_value(chunks)
        return role, subject, scenarios, value

    return role, body[-2], [], body[-1]
