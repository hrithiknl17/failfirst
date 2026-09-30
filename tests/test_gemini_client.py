import json

import httpx
import pytest

from llm import GeminiClient, LLMError

SCHEMA = {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"}}}


def answer(payload, finish="STOP", thought=None):
    parts = [{"text": thought, "thought": True}] if thought else []
    parts.append({"text": json.dumps(payload)})
    return {"candidates": [{"content": {"parts": parts}, "finishReason": finish}]}


def client_with(*responses):
    """GeminiClient whose HTTP layer replays the given (status, json) pairs."""
    queue = list(responses)
    seen = []

    def handler(request):
        seen.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    client = GeminiClient(api_key="test-key", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    return client, seen


def call(client):
    return client.generate_json(model="gemini-x", system="sys", prompt="hi", schema=SCHEMA)


def test_success_sends_schema_and_key_and_parses_json():
    client, seen = client_with((200, answer({"ok": True})))
    assert call(client) == {"ok": True}
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-x:generateContent")
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["generationConfig"]["responseSchema"] == SCHEMA
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


def test_thought_parts_are_ignored():
    client, _ = client_with((200, answer({"ok": True}, thought="thinking...")))
    assert call(client) == {"ok": True}


def test_retries_rate_limit_then_succeeds():
    client, seen = client_with((429, {"error": "slow down"}), (200, answer({"ok": True})))
    assert call(client) == {"ok": True}
    assert len(seen) == 2


def test_gives_up_after_retries():
    client, seen = client_with(*[(503, {"error": "down"})] * 3)
    with pytest.raises(LLMError, match="after 3 attempts"):
        call(client)
    assert len(seen) == 3


def test_client_error_is_not_retried():
    client, seen = client_with((400, {"error": "bad schema"}))
    with pytest.raises(LLMError, match="HTTP 400"):
        call(client)
    assert len(seen) == 1


def test_blocked_prompt_raises():
    client, _ = client_with((200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError, match="SAFETY"):
        call(client)


def test_truncated_answer_raises():
    client, _ = client_with((200, answer({"ok": True}, finish="MAX_TOKENS")))
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        call(client)


def test_invalid_json_raises():
    bad = {"candidates": [{"content": {"parts": [{"text": "not json"}]}, "finishReason": "STOP"}]}
    client, _ = client_with((200, bad))
    with pytest.raises(LLMError, match="invalid JSON"):
        call(client)


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiClient()
