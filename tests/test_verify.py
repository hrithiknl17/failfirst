import pytest
"""The verify loop with a fake runner: no browser, no LLM."""
from pathlib import Path

from generation import GeneratedTest
from verification import RunResult, verify

GOOD = "def test_ok(page):\n    page.goto('/')\n"
OTHER = "def test_other(page):\n    page.goto('/')\n"
UNSAFE = "import os\n\ndef test_bad(page):\n    pass\n"


class Generator:
    def __init__(self, *codes):
        self.codes = list(codes)
        self.feedback = []

    def __call__(self, feedback):
        self.feedback.append(feedback)
        return GeneratedTest(self.codes.pop(0), "checks")


class Runner:
    """outcomes[(code, which)] -> outcome; which is 'pr' or 'base' (from the workdir name)."""

    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls = []

    def __call__(self, code, url, workdir: Path, fixed_time=None):
        which = "pr" if workdir.name.endswith("-pr") else "base"
        self.calls.append((code, which))
        outcome = self.outcomes[(code, which)]
        return RunResult(outcome, f"output for {which}", "SNAP" if outcome == "failed" else "")


def run(gen, runner, tmp_path, **kwargs):
    kwargs.setdefault("stability_reruns", 0)
    kwargs.setdefault("stability_clocks", ())
    return verify(gen, head_url="http://pr", base_url="http://base", workdir=tmp_path, run=runner, **kwargs)


def test_verified_when_passes_on_pr_and_fails_on_base(tmp_path):
    gen = Generator(GOOD)
    result = run(gen, Runner({(GOOD, "pr"): "passed", (GOOD, "base"): "failed"}), tmp_path)
    assert result.status == "verified"
    assert [a.verdict for a in result.attempts] == ["verified"]
    assert gen.feedback == [None]


def test_retry_after_pr_failure_gets_output_and_dom_snapshot(tmp_path):
    gen = Generator(GOOD, OTHER)
    runner = Runner({(GOOD, "pr"): "failed", (OTHER, "pr"): "passed", (OTHER, "base"): "failed"})
    result = run(gen, runner, tmp_path)
    assert result.status == "verified"
    assert result.test.code == OTHER
    fb = gen.feedback[1]
    assert (fb.kind, fb.previous_code, fb.failure_snapshot) == ("failed_on_head", GOOD, "SNAP")
    assert "output for pr" in fb.details


def test_passing_on_base_means_the_test_does_not_cover_the_change(tmp_path):
    gen = Generator(GOOD, GOOD)
    result = run(gen, Runner({(GOOD, "pr"): "passed", (GOOD, "base"): "passed"}), tmp_path)
    assert result.status == "unverified"
    assert "also passes on the base build" in result.reason
    assert gen.feedback[1].kind == "passed_on_base"


def test_unsafe_code_is_never_run(tmp_path):
    gen = Generator(UNSAFE, UNSAFE)
    runner = Runner({})
    result = run(gen, runner, tmp_path)
    assert result.status == "unverified"
    assert runner.calls == []
    assert "import of 'os'" in gen.feedback[1].details


def test_only_one_retry(tmp_path):
    gen = Generator(GOOD, GOOD, GOOD)
    result = run(gen, Runner({(GOOD, "pr"): "failed"}), tmp_path)
    assert result.status == "unverified"
    assert len(result.attempts) == 2
    assert len(gen.codes) == 1  # third generation never requested


def test_base_infrastructure_error_stops_without_retry(tmp_path):
    gen = Generator(GOOD, OTHER)
    result = run(gen, Runner({(GOOD, "pr"): "passed", (GOOD, "base"): "error"}), tmp_path)
    assert result.status == "unverified"
    assert [a.verdict for a in result.attempts] == ["base_error"]
    assert len(gen.feedback) == 1


# --- stability gate ----------------------------------------------------------

class ClockRunner:
    """PR build passes only between 08:00 and 20:30 (like liquid-financial's morning brief)."""

    def __init__(self, pinned_codes=()):
        self.pinned = set(pinned_codes)  # codes that pin their own clock -> always pass on PR
        self.calls = []

    def __call__(self, code, url, workdir, fixed_time=None):
        self.calls.append((url, fixed_time))
        if url == "http://base":
            return RunResult("failed", "E   element(s) not found")
        if code in self.pinned or fixed_time is None:
            return RunResult("passed", "")
        hour = int(fixed_time.split("T")[1][:2])
        ok = 8 <= hour < 20
        return RunResult("passed" if ok else "failed", "" if ok else "E   element(s) not found", "URL: /\n- banner")


def gated(gen, runner, tmp_path):
    return verify(gen, head_url="http://pr", base_url="http://base", workdir=tmp_path, run=runner,
                  stability_reruns=2, today="2026-09-30")  # default clocks: Wed 03/13/22:00 + Sun 21:00


def test_time_dependent_test_is_not_verified(tmp_path):
    gen = Generator(GOOD, GOOD)
    result = gated(gen, ClockRunner(), tmp_path)
    assert result.status == "unverified"
    assert result.diagnosis == "unstable"
    assert "PR build with clock at Wed 03:00: failed, expected passed" in result.reason
    assert "PR build with clock at Wed 22:00: failed, expected passed" in result.reason
    assert "PR build with clock at Sun 21:00: failed, expected passed" in result.reason
    assert "13:00" not in result.reason
    fb = gen.feedback[1]
    assert fb.kind == "unstable" and "03:00" in fb.details


def test_retry_that_pins_the_clock_is_verified(tmp_path):
    gen = Generator(GOOD, OTHER)
    runner = ClockRunner(pinned_codes={OTHER})
    result = gated(gen, runner, tmp_path)
    assert result.status == "verified"
    assert result.test.code == OTHER
    assert "10 stability checks" in result.reason
    assert "Wed 03:00, Wed 13:00, Wed 22:00, Sun 21:00" in result.reason
    # 2 reruns + 3 clocks x (PR + base), plus the first PR and base run, for the verified attempt
    assert ("http://base", "2026-09-30T22:00:00") in runner.calls
    assert ("http://base", "2026-09-27T21:00:00") in runner.calls


@pytest.mark.parametrize("today, weekday, sunday", [
    ("2026-09-30", "2026-09-30", "2026-09-27"),  # Wednesday -> itself, previous Sunday
    ("2026-09-28", "2026-09-28", "2026-09-27"),  # Monday
    ("2026-10-02", "2026-10-02", "2026-09-27"),  # Friday
    ("2026-10-03", "2026-10-02", "2026-09-27"),  # Saturday -> Friday before
    ("2026-10-04", "2026-10-02", "2026-09-27"),  # Sunday -> Friday before, and the Sunday before that
])
def test_clock_dates_pick_a_weekday_and_the_sunday_before_it(today, weekday, sunday):
    from verification.verify import clock_dates
    got = clock_dates(today)
    assert (got[0].isoformat(), got[1].isoformat()) == (weekday, sunday)
    assert got[0].weekday() < 5 and got[1].weekday() == 6
