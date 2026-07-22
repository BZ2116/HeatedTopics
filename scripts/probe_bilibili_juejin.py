"""Read-only recon: confirm real response shapes for Bilibili / Juejin APIs.

Not part of the business code. Run this when online to verify (or invalidate)
the field-name assumptions baked into the parser specs.

Usage:
    uv run python scripts/probe_bilibili_juejin.py

Observed findings (recorded 2026-07-22, online run):
- Bilibili `GET https://api.bilibili.com/x/web-interface/nav`:
    `data.wbi_img` is an object with keys `["img_url", "sub_url"]`. Both
    values are full PNG URLs under `https://i0.hdslb.com/bfs/wbi/...`.
- Juejin `POST https://api.juejin.cn/search_api/v1/search`
    with `{"key_word":"AI","id_type":2,"limit":1,"cursor":"0","search_type":0}`:
    HTTP 200; top-level `err_no == 0`, `err_msg == "success"`;
    `data` is a list of length 20 (note: server returned 20 even though
    `limit` was 1 — server-side limit override). Each item's keys are
    `["result_type", "result_model", "search_attached_info",
    "title_highlight", "content_highlight"]` — the article payload is
    nested under `result_model`, not at the top level.

If the network is unreachable, the script captures errors per-endpoint and
still prints a JSON object so the call site (CI, TDD) does not fail.

This script is informational. It writes nothing to disk and is not loaded
by the pipeline.
"""
from __future__ import annotations

import json
import urllib.request

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BILIBILI_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_REFERER = "https://www.bilibili.com"

JUEJIN_SEARCH_URL = "https://api.juejin.cn/search_api/v1/search"
JUEJIN_REFERER = "https://juejin.cn/"
JUEJIN_PAYLOAD = {
    "key_word": "AI",
    "id_type": 2,
    "limit": 1,
    "cursor": "0",
    "search_type": 0,
}


def _get(url: str, referer: str) -> str:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Referer", referer)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _post_json(url: str, referer: str, payload: dict) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("User-Agent", UA)
    req.add_header("Referer", referer)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def probe_bilibili_nav() -> dict:
    out: dict = {}
    try:
        body = _get(BILIBILI_NAV_URL, BILIBILI_REFERER)
        payload = json.loads(body)
        wbi = payload.get("data", {}).get("wbi_img", {})
        out["wbi_img_keys"] = list(wbi.keys())
        out["wbi_img_sample"] = {
            k: wbi.get(k, "")[:80] for k in list(wbi.keys())[:2]
        }
    except Exception as exc:
        out["error"] = repr(exc)
    return out


def probe_juejin_search() -> dict:
    out: dict = {}
    try:
        status, body = _post_json(
            JUEJIN_SEARCH_URL, JUEJIN_REFERER, JUEJIN_PAYLOAD
        )
        out["http_status"] = status
        payload = json.loads(body) if body else {}
        out["err_no"] = payload.get("err_no")
        out["err_msg"] = payload.get("err_msg")
        data = payload.get("data")
        out["data_is_list"] = isinstance(data, list)
        out["data_length"] = len(data) if isinstance(data, list) else None
        if isinstance(data, list) and data:
            first = data[0]
            out["first_item_keys"] = (
                list(first.keys()) if isinstance(first, dict) else None
            )
    except Exception as exc:
        out["error"] = repr(exc)
    return out


def probe() -> dict:
    return {
        "bilibili_nav": probe_bilibili_nav(),
        "juejin_search": probe_juejin_search(),
    }


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))