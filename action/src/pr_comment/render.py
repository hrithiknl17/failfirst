"""Render the PR comment from a pipeline result. Pure text: no network.

Only a VERIFIED result carries test code. An UNVERIFIED result explains why
and deliberately shows no code — posting code nobody could verify is the thing
this tool exists to prevent.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional

MARKER = "<!-- prgen:comment -->"
MAX_ERROR_CHARS = 1500

_VERDICT_TEXT = {
    "rejected": "rejected by the safety check before running",
    "failed_on_head": "failed on the PR build",
    "passed_on_base": "also passed on the base build (didn't cover the change)",
    "base_error": "could not run on the base build",
    "unstable": "not stable across reruns / times of day",
    "verified": "verified",
}


def safe_text(text: str) -> str:
    """LLM- and PR-derived prose: no HTML, no @mentions, no stray formatting tricks."""
    text = html.escape(" ".join(str(text).split()), quote=False)
    return re.sub(r"@(?=\w)", "@​", text)  # zero-width space: shows "@x" but pings nobody


def fence(code: str, lang: str = "") -> str:
    """A code fence longer than any backtick run inside the code, so it can't be broken out of."""
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{code.rstrip()}\n{ticks}"


def new_file_patch(repo_path: str, code: str) -> str:
    """A git-apply-able unified diff that creates ``repo_path`` with ``code``."""
    lines = code.rstrip("\n").split("\n")
    body = "\n".join("+" + line for line in lines)
    return (
        f"diff --git a/{repo_path} b/{repo_path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{repo_path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n"
        f"{body}\n"
    )


def render_comment(result: Dict[str, Any], *, test_repo_path: str = "") -> str:
    status = result.get("status")
    classification = result.get("classification") or {}
    verification = result.get("verification") or {}
    change = safe_text(classification.get("reason", ""))

    if status == "verified":
        return _verified(change, verification, test_repo_path)
    if status == "unverified":
        return _unverified(change, verification)
    if status == "no_test_needed":
        return "\n".join([MARKER, "### ➖ No UI test needed", "", change, _footer()])
    error = safe_text(result.get("error", "unknown error"))[:MAX_ERROR_CHARS]
    return "\n".join([
        MARKER, "### ❌ Test generation could not finish", "",
        f"**Error:** {error}", "", "No test was posted.", _footer(),
    ])


def _verified(change: str, verification: Dict[str, Any], test_repo_path: str) -> str:
    test = verification.get("test") or {}
    code = test.get("code", "")
    attempts = verification.get("attempts") or []
    out: List[str] = [
        MARKER,
        "### ✅ Playwright test — VERIFIED",
        "",
        f"**Change:** {change}",
        f"**What the test checks:** {safe_text(test.get('what_it_checks', ''))}",
        "",
        "**Verified before you saw this:**",
        "",
        "| Check | Result |",
        "|---|---|",
        "| Runs against the PR build | ✅ passes |",
        "| Runs against the base build (before this PR) | ✅ fails, as it should |",
        f"| Stability | ✅ {safe_text(_stability_summary(verification.get('reason', '')))} |",
        "",
        f"**Suggested file:** `{test_repo_path}`" if test_repo_path else "**Suggested test:**",
        "",
        fence(code, "python"),
    ]
    if test_repo_path:
        out += [
            "",
            "<details><summary>Apply as a patch</summary>",
            "",
            "Save as `prgen.patch` in the repo root, then run `git apply prgen.patch`.",
            "",
            fence(new_file_patch(test_repo_path, code), "diff"),
            "",
            "</details>",
        ]
    out += [
        "",
        "<details><summary>Run it locally</summary>",
        "",
        fence(
            "pip install pytest-playwright && python -m playwright install chromium\n"
            "npm run build && npm run preview -- --port 4173 &\n"
            f"pytest {test_repo_path or '<test file>'} --base-url http://localhost:4173",
            "sh",
        ),
        "",
        "</details>",
        _footer(f"attempt {len(attempts)} of 2"),
    ]
    return "\n".join(out)


def _unverified(change: str, verification: Dict[str, Any]) -> str:
    out: List[str] = [
        MARKER,
        "### ⚠️ Playwright test — UNVERIFIED (not posted)",
        "",
        f"**Change:** {change}",
        "",
        f"**Why there is no test:** {safe_text(verification.get('reason', ''))}",
        "",
        "Attempts:",
    ]
    for attempt in verification.get("attempts") or []:
        verdict = attempt.get("verdict", "")
        out.append(f"- Attempt {attempt.get('number')}: {_VERDICT_TEXT.get(verdict, safe_text(verdict))}")
    out += [
        "",
        "The generated code is intentionally not shown: only tests that pass against a real build are posted.",
        _footer(),
    ]
    return "\n".join(out)


def _stability_summary(reason: str) -> str:
    match = re.search(r"held through (.+)$", reason)
    return f"held through {match.group(1)}" if match else "held"


def _footer(extra: Optional[str] = None) -> str:
    parts = ["Generated and verified by prgen", "never commits to your branch"]
    if extra:
        parts.insert(1, extra)
    return "\n<sub>" + " · ".join(parts) + "</sub>"
