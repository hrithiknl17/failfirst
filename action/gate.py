"""Decide whether this workflow run may generate a test — before any PR code runs.

Standard library only: this is the Action's first step, before Python
dependencies are installed and before the PR's own ``npm ci`` could execute
install scripts. Fork PRs stop here.

    python action/gate.py --event "$GITHUB_EVENT_PATH" --repository "$GITHUB_REPOSITORY"

Writes ``skip`` and ``reason`` to ``$GITHUB_OUTPUT``; when skipping, also a
note to ``$GITHUB_STEP_SUMMARY`` (a fork PR's token is read-only, so the job
summary is the only place a skip notice can go).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple

FORK_REASON = (
    "Fork PR: under the pull_request trigger GitHub gives fork PRs no secrets and a read-only token, "
    "so no test is generated and no PR comment can be posted. A maintainer can push the branch to "
    "this repo to get a verified test."
)
NO_KEY_REASON = (
    "No GEMINI_API_KEY secret is available to this run (not configured for the repo, or a Dependabot PR)."
)


def decide(event: Dict[str, Any], repository: str, has_key: bool) -> Tuple[bool, str]:
    """(skip, reason)."""
    pr = event.get("pull_request")
    if not isinstance(pr, dict):
        return True, "Not a pull_request event."
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    if head_repo != repository:
        return True, FORK_REASON
    if not has_key:
        return True, NO_KEY_REASON
    return False, ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="failfirst-gate")
    parser.add_argument("--event", required=True, help="path to the GitHub event JSON")
    parser.add_argument("--repository", required=True, help="owner/name of the repo running the workflow")
    args = parser.parse_args(argv)

    with open(args.event, encoding="utf-8") as fh:
        event = json.load(fh)
    skip, reason = decide(event, args.repository, os.environ.get("FAILFIRST_HAS_KEY") == "true")

    _append(os.environ.get("GITHUB_OUTPUT"), f"skip={'true' if skip else 'false'}\nreason={reason}\n")
    if skip:
        _append(os.environ.get("GITHUB_STEP_SUMMARY"), f"### ➖ PR test generation skipped\n\n{reason}\n")
        print(f"skipped: {reason}")
    else:
        print("gate passed: same-repo PR with a Gemini key")
    return 0


def _append(path, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


if __name__ == "__main__":
    sys.exit(main())
