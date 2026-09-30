"""Generate -> check -> run on PR build -> run on base build, with one retry.

VERIFIED means: passed the safety check, PASSED on the PR build, FAILED on the
base build, and then held that result through the stability gate (reruns plus
the browser clock set to other times of day, and to a Sunday evening). Anything else after the retry is
UNVERIFIED and never posted as a test.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from generation import Feedback, GeneratedTest, check_test_code

from .runner import RunResult, run_test

MAX_GENERATIONS = 2  # the first try plus exactly one retry
STABILITY_RERUNS = 2
# (day, time): night, day and evening on a weekday catch time-of-day UI; a
# Sunday evening catches weekly UI (e.g. a review that only shows on Sundays).
STABILITY_CLOCKS: Tuple[Tuple[str, str], ...] = (
    ("weekday", "03:00"), ("weekday", "13:00"), ("weekday", "22:00"), ("sunday", "21:00"),
)


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
    stability_clocks: Sequence[Tuple[str, str]] = STABILITY_CLOCKS,
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
            stability_reruns, stability_clocks, today or datetime.date.today(),
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
            f"({stability_reruns} reruns, clock at {', '.join(_clock_label(c, today) for c in stability_clocks)})",
            test, attempts, diagnosis="verified",
        )

    last = attempts[-1]
    reason = _REASONS[last.verdict]
    if last.stability:
        reason += ": " + "; ".join(last.stability)
    return VerificationResult(
        "unverified", f"{reason} (after {len(attempts)} attempt(s))", last.test, attempts, diagnosis=last.verdict
    )


def clock_dates(today=None) -> Tuple[datetime.date, datetime.date]:
    """(weekday, sunday) to fake: today if Mon-Fri, else the Friday before; and the Sunday before that."""
    today = _as_date(today)
    weekday = today if today.weekday() < 5 else today - datetime.timedelta(days=today.weekday() - 4)
    sunday = weekday - datetime.timedelta(days=weekday.weekday() + 1)
    return weekday, sunday


def clock_time(clock: Tuple[str, str], today=None) -> str:
    """ISO local datetime for a (day, time) clock, e.g. ("sunday", "21:00") -> "2026-09-27T21:00:00"."""
    weekday, sunday = clock_dates(today)
    day = sunday if clock[0] == "sunday" else weekday
    return f"{day.isoformat()}T{clock[1]}:00"


def _clock_label(clock: Tuple[str, str], today=None) -> str:
    day = datetime.date.fromisoformat(clock_time(clock, today)[:10])
    return f"{day.strftime('%a')} {clock[1]}"


def _as_date(value) -> datetime.date:
    if value is None:
        return datetime.date.today()
    if isinstance(value, str):
        return datetime.date.fromisoformat(value)
    return value


def _stability_check(code, head_url, base_url, workdir, run, reruns, clocks, today):
    """Returns (deviations, first failing output, first failure snapshot)."""
    checks = [(f"PR build rerun {i + 1}", head_url, None, "passed") for i in range(reruns)]
    for clock in clocks:
        fixed = clock_time(clock, today)
        label = _clock_label(clock, today)
        checks.append((f"PR build with clock at {label}", head_url, fixed, "passed"))
        checks.append((f"base build with clock at {label}", base_url, fixed, "failed"))

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
