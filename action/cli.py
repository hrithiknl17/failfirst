"""Run pipeline steps from the command line.

    python action/cli.py classify --repo ../liquid-financial-sandbox --base master --head my-branch
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import settings  # noqa: E402
from classification import Classification, ClassificationError, classify  # noqa: E402
from diff_extraction import DiffError, DiffResult, extract_diff  # noqa: E402
from llm import GeminiClient  # noqa: E402

_STATUS_LETTER = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="prgen")
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser("classify", help="extract the diff and decide whether it needs a test")
    p_classify.add_argument("--repo", required=True, help="path to the target git checkout")
    p_classify.add_argument("--base", required=True, help="base ref (e.g. master)")
    p_classify.add_argument("--head", required=True, help="head ref (e.g. the PR branch)")
    p_classify.add_argument("--title", default="", help="PR title")
    p_classify.add_argument("--body", default="", help="PR description")
    p_classify.add_argument("--json", action="store_true", help="print machine-readable JSON")

    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # not a real stream (e.g. under some test runners)
        pass
    return _classify(args)


def _classify(args) -> int:
    try:
        diff = extract_diff(args.repo, args.base, args.head)
        llm = GeminiClient() if os.environ.get("GEMINI_API_KEY") else None
        result = classify(
            diff, llm, model=settings.classify_model(), pr_title=args.title, pr_body=args.body
        )
    except (DiffError, ClassificationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"diff": _diff_summary(diff), "classification": asdict(result)}, indent=2))
    else:
        _print_report(diff, result)
    return 0


def _diff_summary(diff: DiffResult) -> dict:
    return {
        "base": diff.base,
        "head": diff.head,
        "files": [
            {"path": f.path, "status": f.status, "added": f.added, "removed": f.removed,
             "binary": f.binary, "truncated": f.truncated}
            for f in diff.files
        ],
        "dropped": [{"path": p, "reason": r} for p, r in diff.dropped],
    }


def _print_report(diff: DiffResult, result: Classification) -> None:
    print(f"Diff {diff.base}...{diff.head}: {len(diff.files)} file(s) kept, {len(diff.dropped)} dropped")
    for f in diff.files:
        flags = "".join([" [binary]" if f.binary else "", " [truncated]" if f.truncated else ""])
        print(f"  {_STATUS_LETTER.get(f.status, '?')} {f.path} (+{f.added} -{f.removed}){flags}")
    for path, reason in diff.dropped:
        print(f"  - {path} ({reason})")
    print()
    verdict = "TEST NEEDED" if result.user_facing else "NO TEST NEEDED"
    print(f"Decision: {verdict} (confidence: {result.confidence}, decided by: {result.decided_by})")
    print(f"Reason:   {result.reason}")
    for area in result.affected_areas:
        print(f"Affected: {area.description}")
        print(f"          where: {area.where_in_ui}; files: {', '.join(area.files) or '-'}")
    if result.test_idea:
        print(f"Test idea: {result.test_idea}")


if __name__ == "__main__":
    sys.exit(main())
