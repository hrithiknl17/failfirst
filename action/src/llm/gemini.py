"""Minimal Gemini client: one JSON-returning call over REST.

Both LLM steps need exactly one thing — "given this system prompt and user
prompt, return JSON matching this schema" — so that is the whole interface.
Swapping providers means writing another class with ``generate_json``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, Optional, Protocol

import httpx

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """The model call failed or returned something we can't use."""


class LLMClient(Protocol):
    def generate_json(
        self, *, model: str, system: str, prompt: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        ...


class GeminiClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        timeout: float = 120.0,
        max_retries: int = 2,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set")
        self._http = httpx.Client(
            base_url=API_BASE,
            timeout=timeout,
            transport=transport,
            headers={"x-goog-api-key": key},
        )
        self._max_retries = max_retries
        self._sleep = sleep

    def generate_json(
        self, *, model: str, system: str, prompt: str, schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        url = f"/models/{model}:generateContent"
        last_problem = ""
        for attempt in range(self._max_retries + 1):
            if attempt:
                self._sleep(2.0 ** attempt)
            try:
                resp = self._http.post(url, json=body)
            except httpx.TransportError as exc:
                last_problem = f"network error: {exc}"
                continue
            if resp.status_code in _RETRYABLE:
                last_problem = f"HTTP {resp.status_code}: {resp.text[:300]}"
                continue
            if resp.status_code != 200:
                raise LLMError(f"Gemini {model} returned HTTP {resp.status_code}: {resp.text[:500]}")
            return _parse_response(resp.json(), model)
        raise LLMError(f"Gemini {model} failed after {self._max_retries + 1} attempts ({last_problem})")


def _parse_response(data: Dict[str, Any], model: str) -> Dict[str, Any]:
    candidates = data.get("candidates") or []
    if not candidates:
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        raise LLMError(f"Gemini {model} returned no answer" + (f" (prompt blocked: {blocked})" if blocked else ""))
    candidate = candidates[0]
    finish = candidate.get("finishReason")
    if finish not in (None, "STOP"):
        raise LLMError(f"Gemini {model} stopped early: {finish}")
    parts = (candidate.get("content") or {}).get("parts") or []
    # Thinking models may return thought parts; only the answer parts matter.
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Gemini {model} returned invalid JSON: {text[:300]!r}") from exc
    if not isinstance(parsed, dict):
        raise LLMError(f"Gemini {model} returned JSON that is not an object: {text[:300]!r}")
    return parsed
