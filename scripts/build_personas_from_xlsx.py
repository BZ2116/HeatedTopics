"""Convert persona xlsx rows into config/profiles/{user_id}.json (v2 schema).

Usage:
    python tmp_3users_test/build_personas_from_xlsx.py --use-llm
    python tmp_3users_test/build_personas_from_xlsx.py --no-llm --regenerate

Default LM behavior = heuristic only (offline-friendly). Pass --use-llm to
route each row through `structure_persona`. LLM failures gracefully fall
back to the heuristic so a flaky network won't break the batch.

The script deduplicates by `(slug, level2)`: if a profile file already
exists with the same level2, the row is skipped (zhao_001 falls under
this — its hand-curated version is preserved).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from heated_topics_v3.llm_client import LLMUnavailable  # noqa: E402
from heated_topics_v3.persona_slugs import (  # noqa: E402
    FALLBACK_KEYWORDS,
    LEVEL2_SLUG,
)
from heated_topics_v3.persona_structurer import (  # noqa: E402
    PersonaStructureError,
    _split_heuristic,
    extract_short_keywords,
    structure_persona,
)

DEFAULT_XLSX = Path(
    "E:/Tencent/WeChat/xwechat_files/wxid_vg07qwjotg2v22_6dbb/"
    "msg/file/2026-07/人设数据收集.xlsx"
)
DEFAULT_OUT = REPO_ROOT / "config" / "profiles"
DEFAULT_HDR = ("一级赛道", "二级赛道", "人设")

# Hand-curated profiles that must never be overwritten, even with --regenerate.
# Currently just zhao_001 (科技AI/AI工具应用) — its persona was tuned manually
# and should survive every script run.
PRESERVED_USER_IDS: set[str] = {"zhao_001"}


def _row_to_payload(level1: str, level2: str, persona_text: str, *, use_llm: bool) -> dict:
    if use_llm:
        try:
            personal = structure_persona(level1, level2, persona_text)
        except (LLMUnavailable, PersonaStructureError) as exc:
            print(f"  [fallback→heuristic] {level1}/{level2}: {exc}", file=sys.stderr)
            personal = _heuristic_to_personal(level1, level2, persona_text)
    else:
        personal = _heuristic_to_personal(level1, level2, persona_text)

    core = list(extract_short_keywords(level1, level2, persona_text))
    return {
        "user_id": "",  # filled by caller after collision check
        "level1": level1,
        "level2": level2,
        "personal": {
            "role": personal.role,
            "subject": personal.subject,
            "scenarios": list(personal.scenarios),
            "value": personal.value,
        },
        "core_keywords": core,
    }


def _heuristic_to_personal(level1: str, level2: str, persona_text: str):
    """Wrap the heuristic splitter into a PersonaPersonal-shaped object."""
    from heated_topics_v3.contracts import PersonaPersonal

    role, subject, scenarios, value = _split_heuristic(persona_text)
    if not role:
        role = level1
    if not subject:
        subject = level2
    if not value:
        value = f"围绕{level2}分享"
    if not scenarios:
        scenarios = _core_keywords(level2, [])
    return PersonaPersonal(
        role=role, subject=subject,
        scenarios=tuple(scenarios[:6]), value=value,
    )


def _core_keywords(level2: str, scenarios: Iterable[str]) -> list[str]:
    fb = FALLBACK_KEYWORDS.get(level2, [level2])
    out: list[str] = []
    seen: set[str] = set()
    for src in (list(scenarios), fb):
        for kw in src:
            kw = str(kw).strip()
            if kw and kw not in seen:
                out.append(kw)
                seen.add(kw)
            if len(out) >= 3:
                break
        if len(out) >= 3:
            break
    return out


def _iter_rows(xlsx: Path):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    col = {name: idx for idx, name in enumerate(header)}
    for row in rows[1:]:
        level1 = row[col[DEFAULT_HDR[0]]]
        level2 = row[col[DEFAULT_HDR[1]]]
        persona_text = row[col[DEFAULT_HDR[2]]]
        if not (level1 and level2 and persona_text):
            continue
        yield level1, level2, persona_text


def _user_id(
    level2: str,
    counter: int,
    existing_stems: set[str],
    generated_user_ids: set[str],
) -> str:
    slug = LEVEL2_SLUG.get(level2, "persona")
    user_id = f"{slug}_{counter:03d}"
    while user_id in existing_stems or user_id in generated_user_ids:
        counter += 1
        user_id = f"{slug}_{counter:03d}"
    return user_id


def main(
    *,
    xlsx: Path = DEFAULT_XLSX,
    out_dir: Path = DEFAULT_OUT,
    use_llm: bool = False,
    regenerate: bool = False,
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    existing_stems = {p.stem for p in out_dir.glob("*.json")}
    generated_user_ids: set[str] = set()
    slug_counter: dict[str, int] = {}

    written, skipped = [], []

    for level1, level2, persona_text in _iter_rows(xlsx):
        # Locate an existing file with matching (slug, level2), if any.
        # Three cases:
        #   1. Match exists and user_id is preserved → skip unconditionally.
        #   2. Match exists and --regenerate → overwrite in place.
        #   3. Match exists and not --regenerate → skip.
        #   4. No match → create a new file with next free ID.
        slug = LEVEL2_SLUG.get(level2, "persona")
        existing_match: Path | None = None
        for existing_file in out_dir.glob(f"{slug}_*.json"):
            try:
                payload = json.loads(existing_file.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if payload.get("level2") == level2:
                existing_match = existing_file
                break

        if existing_match and existing_match.stem in PRESERVED_USER_IDS:
            skipped.append((level2, f"preserved ({existing_match.name})"))
            continue
        if existing_match and not regenerate:
            skipped.append((level2, "already exists"))
            continue
        if existing_match:
            user_id = existing_match.stem
            generated_user_ids.add(user_id)
        else:
            slug_counter[level2] = slug_counter.get(level2, 0) + 1
            user_id = _user_id(
                level2, slug_counter[level2], existing_stems, generated_user_ids
            )
            generated_user_ids.add(user_id)

        payload = _row_to_payload(
            level1, level2, str(persona_text), use_llm=use_llm
        )
        payload["user_id"] = user_id

        out_path = out_dir / f"{user_id}.json"
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(out_path)

    print(f"wrote {len(written)} files (use_llm={use_llm})")
    for p in written:
        print(f"  {p}")
    print(f"skipped {len(skipped)} rows:")
    for level2, reason in skipped:
        print(f"  {level2} -> {reason}")
    return 0


def _cli() -> int:
    p = argparse.ArgumentParser(description="Build v2 persona JSON files from an xlsx.")
    p.add_argument("--input", dest="xlsx", type=Path, default=DEFAULT_XLSX)
    p.add_argument("--out", dest="out_dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--use-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--regenerate", action="store_true")
    args = p.parse_args()
    if args.use_llm and args.no_llm:
        print("--use-llm and --no-llm are mutually exclusive", file=sys.stderr)
        return 2
    return main(
        xlsx=args.xlsx,
        out_dir=args.out_dir,
        use_llm=args.use_llm,
        regenerate=args.regenerate,
    )


if __name__ == "__main__":
    raise SystemExit(_cli())
