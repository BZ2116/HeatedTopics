import argparse
from pathlib import Path

from heated_topics_v3 import cli


def test_bilibili_parser_defaults():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    bilibili = sub.add_parser("bilibili")
    cli._add_bilibili_args(bilibili)
    args = parser.parse_args(["bilibili", "--profile", "p.json"])
    assert args.profile == Path("p.json")
    assert args.top_n == 20
    assert args.cache_root == Path("cache")
    assert args.bilibili_cookie_path == Path(".bilibili_cookie")