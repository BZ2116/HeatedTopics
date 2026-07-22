"""Bilibili WBI 签名（w_rid + wts）。纯函数，无网络。

算法与 bilibili-API-collect 公开文档一致：img_key+sub_key 经固定 64 长度
置换表取前 32 位得 mixin_key；参数按 key 排序、剔除值中的 !'()* 字符后
urlencode，附 wts，w_rid = md5(query + mixin_key)。
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_FILTER_CHARS = "!'()*"


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def img_sub_from_nav(nav: dict) -> tuple[str, str]:
    wbi = nav.get("data", {}).get("wbi_img", {})
    img_key = _basename_no_ext(str(wbi.get("img_url", "")))
    sub_key = _basename_no_ext(str(wbi.get("sub_url", "")))
    return img_key, sub_key


def sign_params(
    params: dict,
    *,
    img_key: str,
    sub_key: str,
    wts: int | None = None,
) -> dict:
    mixin_key = get_mixin_key(img_key + sub_key)
    params["wts"] = int(time.time()) if wts is None else wts
    filtered = {
        k: "".join(c for c in str(v) if c not in _FILTER_CHARS)
        for k, v in sorted(params.items())
    }
    query = urllib.parse.urlencode(filtered)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return params


def _basename_no_ext(url: str) -> str:
    tail = url.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[0]