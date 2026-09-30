"""Run pipeline steps from the command line.

    python action/cli.py classify --repo ../liquid-financial-sandbox --base master --head my-branch
    python action/cli.py run      --repo ../liquid-financial-sandbox --base master --head my-branch
    python action/cli.py post     --result out/my-branch/result.json --repo owner/name --pr 12   # dry run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import settings  # noqa: E402
from classification import Classification, ClassificationError, classify  # noqa: E402
from context import DEFAULT_BUILD_CMD, DEFAULT_INSTALL_CMD, DEFAULT_SERVE_CMD  # noqa: E402
from diff_extraction import DiffError, DiffResult, extract_diff  # noqa: E402
from llm import FallbackClient, GeminiClient  # noqa: E402
from pipeline import AppCommands, PipelineResult, run_pipeline, suggested_test_path  # noqa: E402
from pr_comment import GitHubCommenter, PostError, plan_upsert, render_comment  # noqa: E402

_STATUS_LETTER = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="failfirst")
    sub = parser.add_subparsers(dest="command", required=True)

    p_classify = sub.add_parser("classify", help="extract the diff and decide whether it needs a test")
    p_classify.add_argument("--repo", required=True, help="path to the target git checkout")
    p_classify.add_argument("--base", required=True, help="base ref (e.g. master)")
    p_classify.add_argument("--head", required=True, help="head ref (e.g. the PR branch)")
    p_classify.add_argument("--title", default="", help="PR title")
    p_classify.add_argument("--body", default="", help="PR description")
    p_classify.add_argument("--json", action="store_true", help="print machine-readable JSON")

    p_run = sub.add_parser("run", help="classify, then generate and verify a test")
    p_run.add_argument("--repo", required=True, help="path to the target git checkout")
    p_run.add_argument("--event", default="", help="GitHub event JSON; supplies base/head/title/body/name")
    p_run.add_argument("--base", default="", help="base ref (e.g. master)")
    p_run.add_argument("--head", default="", help="head ref (e.g. the PR branch)")
    p_run.add_argument("--name", default="", help="name for output files (default: head ref)")
    p_run.add_argument("--title", default="", help="PR title")
    p_run.add_argument("--body", default="", help="PR description")
    p_run.add_argument("--out", default="out", help="output directory (a subfolder per name)")
    p_run.add_argument("--out-dir", default="", help="exact output directory (overrides --out)")
    p_run.add_argument("--notes-file", default="", help="optional maintainer notes about the app for the model")
    p_run.add_argument("--build-cmd", default=DEFAULT_BUILD_CMD)
    p_run.add_argument("--serve-cmd", default=DEFAULT_SERVE_CMD, help="must contain {port}")
    p_run.add_argument("--install-cmd", default=DEFAULT_INSTALL_CMD)

    p_post = sub.add_parser("post", help="render the PR comment; DRY RUN unless --post is given")
    p_post.add_argument("--result", required=True, help="result.json written by 'run'")
    p_post.add_argument("--repo", required=True, help="owner/name of the GitHub repo")
    p_post.add_argument("--pr", required=True, type=int, help="pull request number")
    p_post.add_argument("--post", action="store_true",
                        help="actually call the GitHub API (needs GITHUB_TOKEN). Without it nothing is sent.")

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:  # not a real stream (e.g. under some test runners)
            pass
    return {"classify": _classify, "run": _run, "post": _post}[args.command](args)


def _classify(args) -> int:
    try:
        diff = extract_diff(args.repo, args.base, args.head)
        llm = _llm()
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


def _post(args) -> int:
    result_path = Path(args.result)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    body = render_comment(result, test_repo_path=suggested_test_path(result.get("name") or result.get("head", "")))
    (result_path.parent / "comment.md").write_text(body, encoding="utf-8")

    if not args.post:
        plan = plan_upsert(args.repo, args.pr, body)
        plan_file = result_path.parent / "comment_request.json"
        plan_file.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(f"DRY RUN - nothing sent to GitHub. Comment: {result_path.parent / 'comment.md'}")
        print(f"Planned request: {plan_file}")
        return 0

    try:
        url = GitHubCommenter(os.environ.get("GITHUB_TOKEN", ""), args.repo, args.pr).upsert(body)
    except PostError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Posted: {url}")
    return 0


def _llm():
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    return FallbackClient(GeminiClient(), settings.fallback_models())


def _pr_from_event(args) -> None:
    """Fill base/head/name/title/body from the event file. Explicit flags win.

    Reading the PR title and body here, instead of passing them through the
    workflow as ${{ github.event... }}, keeps attacker-written text out of shell.
    """
    if not args.event:
        return
    pr = json.loads(Path(args.event).read_text(encoding="utf-8")).get("pull_request") or {}
    args.base = args.base or (pr.get("base") or {}).get("sha", "")
    args.head = args.head or (pr.get("head") or {}).get("sha", "")
    args.name = args.name or (pr.get("head") or {}).get("ref", "")
    args.title = args.title or pr.get("title") or ""
    args.body = args.body or pr.get("body") or ""


def _run(args) -> int:
    _pr_from_event(args)
    if not (args.base and args.head):
        print("error: --base and --head are required (or pass --event)", file=sys.stderr)
        return 2
    name = args.name or args.head
    llm = _llm()
    notes = Path(args.notes_file).read_text(encoding="utf-8") if args.notes_file else ""
    out_dir = Path(args.out_dir) if args.out_dir else Path(args.out) / re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    result = run_pipeline(
        args.repo, args.base, args.head, llm, out_dir, name=name,
        title=args.title, body=args.body, notes=notes,
        commands=AppCommands(build=args.build_cmd, serve=args.serve_cmd, install=args.install_cmd),
        log=lambda msg: print(f"[failfirst {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True),
    )
    _print_run_report(result, out_dir)
    return 2 if result.status == "error" else 0


def _print_run_report(result: PipelineResult, out_dir: Path) -> None:
    print(f"Status: {result.status.upper().replace('_', ' ')}")
    if result.error:
        print(f"Error:  {result.error}")
    if result.classification:
        print(f"Why:    {result.classification.reason}")
    verification = result.verification
    if verification:
        print(f"Verify: {verification.reason}")
        for attempt in verification.attempts:
            runs = []
            if attempt.head:
                runs.append(f"PR build: {attempt.head.outcome}")
            if attempt.base:
                runs.append(f"base build: {attempt.base.outcome}")
            detail = "; ".join(runs) or "; ".join(attempt.problems)
            print(f"  attempt {attempt.number}: {attempt.verdict} ({detail})")
    if result.test_file:
        print(f"Test:   {result.test_file}")
    print(f"Result: {out_dir / 'result.json'}")


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
