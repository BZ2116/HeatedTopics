import httpx

from heated_topics_v3.llm_adapter import LLMAdapter, LLMConfig


def test_shared_adapter_uses_common_config_and_reasoning_split():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request=json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    import json
    adapter = LLMAdapter(LLMConfig("key", "https://llm.test/v1", "model"), client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert adapter.complete(system="s", user="u") == "ok"
    assert seen["request"]["reasoning_split"] is True
