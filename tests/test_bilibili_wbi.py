import hashlib

from heated_topics_v3.bilibili_wbi import get_mixin_key, sign_params, img_sub_from_nav


def test_get_mixin_key_is_32_chars_and_from_source():
    src = "7cd084941338484aae1ad9425b84077c" + "4932caff0ff746eab6f01bf08b70ac45"
    key = get_mixin_key(src)
    assert len(key) == 32
    assert all(ch in src for ch in key)


def test_img_sub_from_nav_extracts_basenames():
    nav = {"data": {"wbi_img": {
        "img_url": "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
        "sub_url": "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png",
    }}}
    img_key, sub_key = img_sub_from_nav(nav)
    assert img_key == "7cd084941338484aae1ad9425b84077c"
    assert sub_key == "4932caff0ff746eab6f01bf08b70ac45"


def test_sign_params_appends_wts_and_valid_w_rid():
    params = {"keyword": "AI", "search_type": "article", "page": 1}
    signed = sign_params(dict(params), img_key="a" * 32, sub_key="b" * 32, wts=1_700_000_000)
    assert signed["wts"] == 1_700_000_000
    assert len(signed["w_rid"]) == 32
    int(signed["w_rid"], 16)


def test_sign_params_is_deterministic_and_input_sensitive():
    a = sign_params({"keyword": "AI"}, img_key="a" * 32, sub_key="b" * 32, wts=100)
    b = sign_params({"keyword": "AI"}, img_key="a" * 32, sub_key="b" * 32, wts=100)
    c = sign_params({"keyword": "ML"}, img_key="a" * 32, sub_key="b" * 32, wts=100)
    assert a["w_rid"] == b["w_rid"]
    assert a["w_rid"] != c["w_rid"]