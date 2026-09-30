"""Generate -> check -> run on PR build -> run on base build, with one retry.

VERIFIED means: passed the safety check, PASSED on the PR build and FAILED on
the base build. Anything else after the retry is UNVERIFIED and never posted
as a test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from generation import Feedback, GeneratedTest, check_test_code

from .runner import RunResult, run_test

MAX_GENERATIONS = 2  # the first try plus exactly one retry


@dataclass
class Attempt:
    number: int
    test: GeneratedTest
    verdict: str  # rejected | failed_on_head | passed_on_base | base_error | verified
    problems: List[str] = field(default_factory=list)
    head: Optional[RunResult] = None
    base: Optional[RunResult] = None


@dataclass
class VerificationResult:
    status: str  # "verified" | "unverified"
    reason: str
    test: Optional[GeneratedTest]
    attempts: List[Attempt]


_REASONS = {
    "rejected": "the generated test broke the safety rules",
    "failed_on_head": "the generated test failed against the PR build",
    "passed_on_base": "the generated test also passes on the base build, so it does not cover this change",
    "base_error": "the generated test could not be run against the base build",
}


def verify(
    generate: Callable[[Optional[Feedback]], GeneratedTest],
    *,
    head_url: str,
    base_url: str,
    workdir: Path,
    max_generations: int = MAX_GENERATIONS,
    run: Callable[[str, str, Path], RunResult] = run_test,
) -> VerificationResult:
    attempts: List[Attempt] = []
    feedback: Optional[Feedback] = None

    for number in range(1, max_generations + 1):
        test = generate(feedback)

        problems = check_test_code(test.code)
        if problems:
            attempts.append(Attempt(number, test, "rejected", problems=problems))
            feedback = Feedback(test.code, "rejected", "\n".join(f"- {p}" for p in problems))
            continue

        head = run(test.code, head_url, workdir / f"attempt{number}-pr")
        if head.outcome != "passed":
            attempts.append(Attempt(number, test, "failed_on_head", head=head))
            feedback = Feedback(test.code, "failed_on_head", head.output, head.failure_snapshot)
            continue

        base = run(test.code, base_url, workdir / f"attempt{number}-base")
        if base.outcome == "passed":
            attempts.append(Attempt(number, test, "passed_on_base", head=head, base=base))
            feedback = Feedback(test.code, "passed_on_base")
            continue
        if base.outcome == "error":
            # Infrastructure problem, not the test's fault: a retry would not help.
            attempts.append(Attempt(number, test, "base_error", head=head, base=base))
            break

        attempts.append(Attempt(number, test, "verified", head=head, base=base))
        return VerificationResult(
            "verified", "passes on the PR build and fails on the base build", test, attempts
        )

    last = attempts[-1]
    return VerificationResult(
        "unverified",
        f"{_REASONS[last.verdict]} (after {len(attempts)} attempt(s))",
        last.test,
        attempts,
    )
