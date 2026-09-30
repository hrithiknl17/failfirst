"""Runtime settings read from the environment, with the defaults logged in decisions.md."""
from __future__ import annotations

import os

DEFAULT_CLASSIFY_MODEL = "gemini-3.1-flash-lite"
DEFAULT_GENERATE_MODEL = "gemini-3.8-flash"


def classify_model() -> str:
    return os.environ.get("PRGEN_CLASSIFY_MODEL") or DEFAULT_CLASSIFY_MODEL


def generate_model() -> str:
    return os.environ.get("PRGEN_GENERATE_MODEL") or DEFAULT_GENERATE_MODEL
