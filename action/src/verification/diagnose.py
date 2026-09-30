"""Turn a failed verification into a reason a human can act on.

"Failed against the PR build" reads like flakiness. Often the real story is
that the changed UI never rendered at all in this build — behind sign-in, a
feature flag, or config the build doesn't have. We can tell those apart: pull
the user-visible text the PR added, and check whether it appeared on any page
verification actually reached.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

from diff_extraction import FileChange

from .verify import VerificationResult

MIN_TEXT_LEN = 4

_STRING_LITERAL = re.compile(r"""'([^'\\\n]+)'|"([^"\\\n]+)"|`([^`$\\\n]+)`""")
_JSX_TEXT = re.compile(r">\s*([^<>{}]+?)\s*<")
_CODEY = re.compile(r"[;=(){}\[\]<>]|=>|\bconst\b|\breturn\b|\bimport\b")


def new_ui_texts(changes: Sequence[FileChange]) -> List[str]:
    """User-visible strings on added lines: JSX text and prose-like string literals."""
    found: List[str] = []
    for change in changes:
        for line in change.patch.split("\n"):
            if not line.startswith("+"):
                continue
            body = line[1:].strip()
            candidates = [m.group(1) for m in _JSX_TEXT.finditer(body)]
            candidates += [next(g for g in m.groups() if g) for m in _STRING_LITERAL.finditer(body)]
            if body and not _CODEY.search(body) and not body.startswith(("//", "/*", "*")):
                candidates.append(body)  # a bare JSX text line
            for text in candidates:
                text = " ".join(text.split())
                if _looks_like_ui_text(text) and text not in found:
                    found.append(text)
    return found


def _looks_like_ui_text(text: str) -> bool:
    if len(text) < MIN_TEXT_LEN or not re.search(r"[A-Za-z]", text):
        return False
    tokens = text.split()
    # Tailwind class lists, paths, URLs, identifiers: not something a user reads.
    if sum(1 for t in tokens if re.search(r"[-:/\[\]_.#]", t)) > len(tokens) / 2:
        return False
    return len(tokens) > 1 or text[:1].isupper()


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def unreached(texts: Iterable[str], snapshots: Iterable[str]) -> List[str]:
    """Texts that appear in none of the snapshots (case/whitespace-insensitive)."""
    seen = [_norm(s) for s in snapshots if s]
    return [t for t in texts if not any(_norm(t) in s for s in seen)]


def first_error_line(pytest_output: str) -> str:
    for line in pytest_output.splitlines():
        if line.startswith("E ") and line[1:].strip():
            return line[1:].strip()
    return ""


def explain(result: VerificationResult, changes: Sequence[FileChange], start_snapshot: str) -> Tuple[str, str]:
    """(reason, diagnosis) for an UNVERIFIED result; verified results pass through."""
    if result.status == "verified" or not result.attempts:
        return result.reason, result.diagnosis
    last = result.attempts[-1]
    tries = f"{len(result.attempts)} attempt(s)"
    if last.verdict != "failed_on_head" or last.head is None:
        return result.reason, result.diagnosis

    texts = new_ui_texts(changes)
    pages = [start_snapshot] + [a.head.failure_snapshot for a in result.attempts if a.head]
    if texts and len(unreached(texts, pages)) == len(texts):
        shown = ", ".join(f"'{t}'" for t in texts[:3])
        return (
            f"change not reachable in this build: none of the new UI text ({shown}) appeared on any page "
            f"verification reached (the start page plus {len(pages) - 1} page(s) where tests failed, "
            f"over {tries}). It likely sits behind sign-in, a feature flag or configuration this build "
            "doesn't have. Not a flaky test: the UI was never there to find.",
            "not_reachable",
        )
    error = first_error_line(last.head.output) or last.head.outcome
    return f"the generated test failed against the PR build after {tries}: {error}", "test_failed"
