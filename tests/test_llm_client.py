import io
import urllib.error

import pytest

from heated_topics_v3.llm_client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMConfig,
    LLMUnavailable,
    call_llm,
)


def test_minimax_defaults_use_current_anthropic_endpoint_and_model():
    assert DEFAULT_BASE_URL == "https://api.minimax.io/anthropic"
    assert DEFAULT_MODEL == "MiniMax-M2.7"


def test_call_llm_includes_sanitized_http_error_body(monkeypatch, tmp_path):
    error = urllib.error.HTTPError(
        url="https://api.minimax.io/anthropic/v1/messages",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"error":{"message":"invalid api key"}}'),
    )

    def fail_urlopen(*_args, **_kwargs):
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    with pytest.raises(LLMUnavailable) as exc_info:
        call_llm(
            "ping",
            config=LLMConfig(
                api_key="secret-value-must-not-appear",
                base_url="https://api.minimax.io/anthropic",
                model="MiniMax-M2.7",
            ),
            cache_dir=tmp_path,
            use_cache=False,
        )

    message = str(exc_info.value)
    assert "HTTP 401" in message
    assert "invalid api key" in message
    assert "secret-value-must-not-appear" not in message
