import argparse
from pathlib import Path

from heated_topics_v3 import cli


def test_juejin_v2_parser_has_profile_v2():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    juejin = sub.add_parser("juejin")
    cli._add_juejin_args(juejin)
    args = parser.parse_args(["juejin", "--profile-v2", "p.json", "--top-n", "5"])
    assert args.profile_v2 == Path("p.json")
    assert args.top_n == 5
