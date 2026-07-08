from src.core_pipeline.model_topic_summarizer import (
    build_creator_topic_synthesis,
    build_model_summaries,
    call_openai_compatible_chat,
    compact_topic_for_model,
    resolve_openai_compatible_chat_config,
)
import json
import urllib.request
from contextlib import contextmanager


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload.encode("utf-8") if isinstance(payload, str) else payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@contextmanager
def _stub_urlopen(captured, response_payload):
    def fake(request, timeout=0):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps(response_payload))

    original = urllib.request.urlopen
    urllib.request.urlopen = fake
    try:
        yield
    finally:
        urllib.request.urlopen = original


def test_compact_topic_for_model_keeps_high_signal_card_fields():
    topic = {
        "title": "河北高考分数线",
        "domain_path": ["教育升学", "高考", "分数线"],
        "content_modes": ["数据整理"],
        "audience_tags": ["学生", "家长"],
        "hotness": {"best_rank": 1, "platforms": ["weibo"]},
        "traceability": "high",
        "risk_level": "low",
        "card": {
            "clean_content": "河北高考分数线公布。本科批历史科目组合485分，物理科目组合443分。",
            "evidence_urls": ["https://example.com/a"],
            "platform_cards": [
                {
                    "platform": "weibo",
                    "clean_content": "微博侧重点是分数线发布和志愿填报讨论。",
                    "url": "https://example.com/weibo",
                }
            ],
        },
    }

    compact = compact_topic_for_model(topic)

    assert compact["title"] == "河北高考分数线"
    assert compact["domain_path"] == ["教育升学", "高考", "分数线"]
    assert compact["hotness"] == {"best_rank": 1, "platforms": ["weibo"]}
    assert "本科批历史科目组合485分" in compact["evidence_excerpt"]
    assert compact["platform_evidence"][0]["platform"] == "weibo"
    assert compact["evidence_urls"] == ["https://example.com/a"]


def test_build_creator_topic_synthesis_normalizes_model_json():
    index = {
        "topics": [
            {
                "title": "河北高考分数线",
                "domain_path": ["教育升学", "高考", "分数线"],
                "content_modes": ["数据整理"],
                "audience_tags": ["学生", "家长"],
                "hotness": {"best_rank": 1, "platforms": ["weibo"]},
                "traceability": "high",
                "risk_level": "low",
                "card": {"clean_content": "河北高考分数线公布。"},
            }
        ]
    }

    def fake_model(messages):
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[1]["content"]
        return {
            "overall_summary": {
                "core_conclusion": "高考分数线话题适合做强时效数据卡。",
                "topic_landscape": "教育升学占主导。",
                "creator_strategy": "优先做分数线表格和志愿填报提醒。",
                "risk_and_verification": "核对官方教育考试院。",
            },
            "theme_clusters": [
                {
                    "theme": "高考数据",
                    "topics": ["河北高考分数线"],
                    "shared_insight": "用户需要快速查分和填报判断。",
                    "content_opportunities": ["分数线表格", "志愿时间线"],
                    "evidence_level": "high",
                }
            ],
            "topic_summaries": {
                "河北高考分数线": {
                    "what_happened": "河北公布高考分数线。",
                    "why_it_matters": "直接影响志愿填报。",
                    "creator_angle": "可做表格解读。",
                    "tracking_hint": "跟进一分一段表。",
                    "key_details": ["历史485分", "物理443分"],
                    "confidence": "high",
                }
            },
        }

    synthesis = build_creator_topic_synthesis(
        index=index,
        model_call=fake_model,
        generated_at="2026-06-25T10:00:00+08:00",
        model="gpt-test",
    )

    assert synthesis["schema_version"] == "1.0"
    assert synthesis["generated_at"] == "2026-06-25T10:00:00+08:00"
    assert synthesis["model"] == "gpt-test"
    assert synthesis["source_topic_count"] == 1
    assert synthesis["overall_summary"]["core_conclusion"] == "高考分数线话题适合做强时效数据卡。"
    assert synthesis["topic_summaries"]["河北高考分数线"]["mode"] == "model"
    assert synthesis["topic_summaries"]["河北高考分数线"]["key_details"] == ["历史485分", "物理443分"]


def test_build_model_summaries_extracts_card_compatible_fields():
    synthesis = {
        "topic_summaries": {
            "河北高考分数线": {
                "mode": "model",
                "what_happened": "河北公布高考分数线。",
                "why_it_matters": "影响志愿填报。",
                "creator_angle": "做表格。",
                "tracking_hint": "跟进一分一段表。",
                "key_details": ["历史485分"],
            }
        }
    }

    summaries = build_model_summaries(synthesis)

    assert summaries == {
        "河北高考分数线": {
            "mode": "model",
            "what_happened": "河北公布高考分数线。",
            "why_it_matters": "影响志愿填报。",
            "creator_angle": "做表格。",
            "tracking_hint": "跟进一分一段表。",
        }
    }


def test_resolve_openai_compatible_chat_config_uses_minimax_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")

    config = resolve_openai_compatible_chat_config(model=None, api_key=None, base_url=None)

    assert config == {
        "api_key": "minimax-key",
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-M3",
    }


def test_resolve_openai_compatible_chat_config_prefers_minimax_over_default_openai_model(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")

    config = resolve_openai_compatible_chat_config(model="gpt-4.1-mini", api_key=None, base_url=None)

    assert config["model"] == "MiniMax-M2.7"


def test_call_openai_compatible_chat_dispatches_to_anthropic_when_url_matches():
    captured: dict = {}
    with _stub_urlopen(captured, {"content": [{"type": "text", "text": '{"a":1}'}]}):
        result = call_openai_compatible_chat(
            messages=[
                {"role": "system", "content": "你是严谨助手。只输出 JSON。"},
                {"role": "user", "content": "归纳这段话"},
            ],
            model="MiniMax-M3",
            api_key="minimax-key",
            base_url="https://api.minimaxi.com/anthropic",
        )

    assert result == {"a": 1}
    assert captured["url"] == "https://api.minimaxi.com/anthropic/v1/messages"
    assert captured["headers"].get("X-api-key") == "minimax-key"
    assert captured["headers"].get("Anthropic-version") == "2023-06-01"
    assert captured["body"]["model"] == "MiniMax-M3"
    assert captured["body"]["system"] == "你是严谨助手。只输出 JSON。"
    assert all(m["role"] != "system" for m in captured["body"]["messages"])
    assert "max_tokens" in captured["body"]


def test_call_openai_compatible_chat_keeps_openai_path_for_default_url():
    captured: dict = {}
    with _stub_urlopen(captured, {"choices": [{"message": {"content": '{"k":"v"}'}}]}):
        result = call_openai_compatible_chat(
            messages=[
                {"role": "system", "content": "只输出 JSON"},
                {"role": "user", "content": "hello"},
            ],
            model="gpt-test",
            api_key="openai-key",
            base_url="https://api.openai.com/v1",
        )

    assert result == {"k": "v"}
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"].get("Authorization") == "Bearer openai-key"
    body = captured["body"]
    assert body["messages"][0]["role"] == "system"
    assert body["response_format"] == {"type": "json_object"}


def test_call_anthropic_chat_parses_multiple_text_blocks_into_json():
    captured: dict = {}
    response = {
        "content": [
            {"type": "text", "text": '{"hello"'},
            {"type": "text", "text": ': "world"}'},
        ]
    }
    with _stub_urlopen(captured, response):
        result = call_openai_compatible_chat(
            messages=[{"role": "user", "content": "ping"}],
            model="MiniMax-M3",
            api_key="k",
            base_url="https://api.minimaxi.com/anthropic",
        )

    assert result == {"hello": "world"}
