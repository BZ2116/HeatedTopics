from src.search_discovery.env_file import ensure_env_file, read_env_values, upsert_env_values


def test_ensure_env_file_copies_example_when_missing(tmp_path):
    example = tmp_path / ".env.example"
    target = tmp_path / ".env"
    example.write_text("TAVILY_API_KEY=\n", encoding="utf-8")

    created = ensure_env_file(target, example)

    assert created is True
    assert target.read_text(encoding="utf-8") == "TAVILY_API_KEY=\n"


def test_read_env_values_ignores_comments_and_blank_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# comment\n\nTAVILY_API_KEY=tvly_fake\nEMPTY=\n", encoding="utf-8")

    values = read_env_values(env_path)

    assert values == {"TAVILY_API_KEY": "tvly_fake", "EMPTY": ""}


def test_upsert_env_values_preserves_comments_and_updates_existing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# Tavily\nTAVILY_API_KEY=old\n\nGITHUB_TOKEN=\n", encoding="utf-8")

    upsert_env_values(env_path, {"TAVILY_API_KEY": "new", "BOCHA_API_KEY": "bocha"})

    assert env_path.read_text(encoding="utf-8") == (
        "# Tavily\n"
        "TAVILY_API_KEY=new\n"
        "\n"
        "GITHUB_TOKEN=\n"
        "BOCHA_API_KEY=bocha\n"
    )