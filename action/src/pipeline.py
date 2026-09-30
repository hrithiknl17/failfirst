"""End to end: diff -> classify -> build both refs -> context -> generate + verify.

Writes ``result.json`` plus the test file into ``out_dir``. A verified test is
written as ``test_failfirst_<branch>.py``; an unverified one only as
``UNVERIFIED_test_failfirst_<branch>.py`` for debugging — it is never posted.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import settings
from classification import Classification, ClassificationError, classify, prefilter
from context import (
    DEFAULT_BUILD_CMD,
    DEFAULT_INSTALL_CMD,
    DEFAULT_SERVE_CMD,
    BuildError,
    build,
    checkout,
    gather,
    merge_base,
    resolve_sha,
    serve,
)
from diff_extraction import DiffError, extract_diff
from generation import GenerationError, generate_test
from llm import LLMClient
from pr_comment import render_comment
from verification import VerificationResult, explain, verify

TEST_DIR = "e2e"


@dataclass(frozen=True)
class AppCommands:
    build: str = DEFAULT_BUILD_CMD
    serve: str = DEFAULT_SERVE_CMD
    install: str = DEFAULT_INSTALL_CMD


@dataclass
class PipelineResult:
    status: str = "error"  # no_test_needed | verified | unverified | error
    head: str = ""
    name: str = ""  # human name for files, e.g. the branch; defaults to head
    classification: Optional[Classification] = None
    verification: Optional[VerificationResult] = None
    test_file: str = ""
    error: str = ""


def generated_test_filename(head: str) -> str:
    # Branches named "failfirst/<x>" would otherwise give test_failfirst_failfirst_<x>.py.
    name = re.sub(r"^failfirst/", "", head, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "change"
    return f"test_failfirst_{slug}.py"


def run_pipeline(
    repo: str,
    base: str,
    head: str,
    llm: Optional[LLMClient],
    out_dir: Path,
    *,
    name: str = "",
    title: str = "",
    body: str = "",
    notes: str = "",
    commands: AppCommands = AppCommands(),
    log: Callable[[str], None] = print,
) -> PipelineResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    result = PipelineResult(head=head, name=name or head)
    try:
        _run(result, repo, base, head, llm, out_dir, title, body, notes, commands, log)
    except (DiffError, ClassificationError, BuildError, GenerationError) as exc:
        result.status, result.error = "error", str(exc)
    data = asdict(result)
    (out_dir / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    # Rendered offline so every run leaves a reviewable comment; sending it is a separate step.
    (out_dir / "comment.md").write_text(
        render_comment(data, test_repo_path=suggested_test_path(result.name)), encoding="utf-8"
    )
    return result


def suggested_test_path(head: str, test_dir: str = TEST_DIR) -> str:
    """Where the suggested test would live in the target repo."""
    return f"{test_dir}/{generated_test_filename(head)}"


def _run(result, repo, base, head, llm, out_dir, title, body, notes, commands, log) -> None:
    log(f"diff {base}...{head}")
    diff = extract_diff(repo, base, head)
    result.classification = classify(diff, llm, model=settings.classify_model(), pr_title=title, pr_body=body)
    if not result.classification.user_facing:
        result.status = "no_test_needed"
        return
    if llm is None:
        raise ClassificationError("generation needs an LLM client (set GEMINI_API_KEY)")

    head_sha = resolve_sha(repo, head)
    base_sha = merge_base(repo, base, head)
    trees = {}
    for label, sha in (("PR", head_sha), ("base", base_sha)):
        log(f"build {label} at {sha[:12]}")
        trees[label] = checkout(repo, sha)
        build(repo, trees[label], build_cmd=commands.build, install_cmd=commands.install)

    changes = prefilter(diff.files).candidates
    with serve(trees["PR"], serve_cmd=commands.serve) as head_url, \
            serve(trees["base"], serve_cmd=commands.serve) as base_url:
        log(f"serving PR at {head_url}, base at {base_url}")
        ctx = gather(repo, head_sha, changes, head_url, notes=notes)

        def generate(feedback):
            log("generate test" + (f" (retry after: {feedback.kind})" if feedback else ""))
            return generate_test(
                result.classification, changes, ctx, llm, model=settings.generate_model(), feedback=feedback
            )

        result.verification = verify(generate, head_url=head_url, base_url=base_url, workdir=out_dir / "runs")

    verification = result.verification
    verification.reason, verification.diagnosis = explain(verification, changes, ctx.aria_snapshot)
    result.status = verification.status
    if verification.test is not None:
        name = generated_test_filename(result.name)
        if verification.status != "verified":
            name = "UNVERIFIED_" + name
        (out_dir / name).write_text(verification.test.code, encoding="utf-8")
        result.test_file = str(out_dir / name)
