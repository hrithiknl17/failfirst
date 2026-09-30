"""Runtime settings read from the environment, with the defaults logged in decisions.md."""
from __future__ import annotations

import os
from typing import Dict, List

DEFAULT_CLASSIFY_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GENERATE_MODEL = "gemini-3.8-flash"

# Tried in order when the primary model is overloaded.
DEFAULT_CLASSIFY_FALLBACKS = ("gemini-3.5-flash-lite", "gemini-2.5-flash-lite")
DEFAULT_GENERATE_FALLBACKS = ("gemini-3.5-flash", "gemini-2.5-flash")


def classify_model() -> str:
    return os.environ.get("PRGEN_CLASSIFY_MODEL") or DEFAULT_CLASSIFY_MODEL


def generate_model() -> str:
    return os.environ.get("PRGEN_GENERATE_MODEL") or DEFAULT_GENERATE_MODEL


def fallback_models() -> Dict[str, List[str]]:
    return {
        classify_model(): _list("PRGEN_CLASSIFY_FALLBACKS", DEFAULT_CLASSIFY_FALLBACKS),
        generate_model(): _list("PRGEN_GENERATE_FALLBACKS", DEFAULT_GENERATE_FALLBACKS),
    }


def _list(env: str, default) -> List[str]:
    raw = os.environ.get(env)
    if raw is None:
        return list(default)
    return [m.strip() for m in raw.split(",") if m.strip()]
