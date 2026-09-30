"""Generate -> check -> run on PR build -> run on base build, with one retry.

VERIFIED means: passed the safety check, PASSED on the PR build, FAILED on the
base build, and then held that result through the stability gate (reruns plus
the browser clock set to other times of day). Anything else after the retry is
UNVERIFIED and never posted as a test.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from generation import Feedback, GeneratedTest, check_test_code

from .runner import RunResult, run_test

MAX_GENERATIONS = 2  # the first try plus exactly one retry
STABILITY_RERUNS = 2
# Night, day, evening: catches UIs that change with the time of day.
STABILITY_CLOCKS = ("03:00", "13:00", "22:00")


@dataclass
class Attempt:
    number: int
    test: GeneratedTest
    verdict: str  # rejected | failed_on_head | passed_on_base | base_error | unstable | verified
    problems: List[str] = field(default_factory=list)
    head: Optional[RunResult] = None
    base: Optional[RunResult] = None
    stability: List[str] = field(default_factory=list)  # deviations found by the gate


@dataclass
class VerificationResult:
    status: str  # "verified" | "unverified"
    reason: str
    test: Optional[GeneratedTest]
    attempts: List[Attempt]
    diagnosis: str = ""  # machine-readable cause, set by diagnose.explain


_REASONS = {
    "rejected": "the generated test broke the safety rules",
    "failed_on_head": "the generated test failed against the PR build",
    "passed_on_base": "the generated test also passes on the base build, so it does not cover this change",
    "base_error": "the generated test could not be run against the base build",
    "unstable": "the generated test is not stable",
}


def verify(
    generate: Callable[[Optional[Feedback]], GeneratedTest],
    *,
    head_url: str,
    base_url: str,
    workdir: Path,
    max_generations: int = MAX_GENERATIONS,
    run: Callable[..., RunResult] = run_test,
    stability_reruns: int = STABILITY_RERUNS,
    stability_clocks: Sequence[str] = STABILITY_CLOCKS,
    today: Optional[str] = None,
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

        deviations, output, snapshot = _stability_check(
            test.code, head_url, base_url, workdir / f"attempt{number}-stability", run,
            stability_reruns, stability_clocks, today or datetime.date.today().isoformat(),
        )
        if deviations:
            attempts.append(Attempt(number, test, "unstable", head=head, base=base, stability=deviations))
            details = "\n".join(f"- {d}" for d in deviations) + "\n\n" + output
            feedback = Feedback(test.code, "unstable", details, snapshot)
            continue

        attempts.append(Attempt(number, test, "verified", head=head, base=base))
        checks = stability_reruns + 2 * len(stability_clocks)
        return VerificationResult(
            "verified",
            f"passes on the PR build and fails on the base build, and held through {checks} stability checks "
            f"({stability_reruns} reruns, clock at {', '.join(stability_clocks)})",
            test, attempts, diagnosis="verified",
        )

    last = attempts[-1]
    reason = _REASONS[last.verdict]
    if last.stability:
        reason += ": " + "; ".join(last.stability)
    return VerificationResult(
        "unverified", f"{reason} (after {len(attempts)} attempt(s))", last.test, attempts, diagnosis=last.verdict
    )


def _stability_check(code, head_url, base_url, workdir, run, reruns, clocks, today):
    """Returns (deviations, first failing output, first failure snapshot)."""
    checks = [(f"PR build rerun {i + 1}", head_url, None, "passed") for i in range(reruns)]
    for clock in clocks:
        fixed = f"{today}T{clock}:00"
        checks.append((f"PR build with clock at {clock}", head_url, fixed, "passed"))
        checks.append((f"base build with clock at {clock}", base_url, fixed, "failed"))

    deviations: List[str] = []
    output = snapshot = ""
    for label, url, fixed, want in checks:
        folder = workdir / label.replace(" ", "-").replace(":", "")
        result = run(code, url, folder, fixed_time=fixed)
        ok = result.outcome == "passed" if want == "passed" else result.outcome != "passed"
        if not ok:
            deviations.append(f"{label}: {result.outcome}, expected {want}")
            if not output:
                output, snapshot = result.output, result.failure_snapshot
    return deviations, output, snapshot
