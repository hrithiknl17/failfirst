"""Path globs with the semantics people expect from .gitignore-style rules.

``fnmatch`` lets ``*`` cross ``/``, so ``*.md`` would also match
``src/content/page.md``. Here ``*`` stays inside one path segment and ``**``
spans segments, which lets rules say "root-level markdown" (``*.md``) and
"markdown anywhere" (``**/*.md``) differently.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional


@lru_cache(maxsize=None)
def _compile(pattern: str) -> "re.Pattern[str]":
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def match(path: str, pattern: str) -> bool:
    return _compile(pattern).match(path) is not None


def first_match(path: str, patterns: Iterable[str]) -> Optional[str]:
    for pattern in patterns:
        if match(path, pattern):
            return pattern
    return None
