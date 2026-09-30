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

    def __call__(self, code, url, workdir: Path):
        which = "pr" if workdir.name.endswith("-pr") else "base"
        self.calls.append((code, which))
        outcome = self.outcomes[(code, which)]
        return RunResult(outcome, f"output for {which}", "SNAP" if outcome == "failed" else "")


def run(gen, runner, tmp_path):
    return verify(gen, head_url="http://pr", base_url="http://base", workdir=tmp_path, run=runner)


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
