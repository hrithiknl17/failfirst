from diff_extraction import FileChange
from generation import GeneratedTest
from verification import Attempt, RunResult, VerificationResult, explain, new_ui_texts, unreached


def change(*added):
    patch = "@@ -1 +1 @@\n" + "\n".join("+" + a for a in added)
    return FileChange("src/X.tsx", "modified", patch)


def test_extracts_jsx_text_and_prose_literals_not_code_or_classes():
    texts = new_ui_texts([change(
        "          Explore the demo ledger",
        "          Add today's spend",
        '  <button className="mt-8 w-full py-3.5 bg-slate-900">Save changes</button>',
        "  const label = isOpen ? 'Hide details' : 'Show details';",
        "  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;",
        "  // a comment about Things",
    )])
    assert texts == ["Explore the demo ledger", "Add today's spend", "Save changes", "Hide details", "Show details"]


def test_unreached_is_case_and_whitespace_insensitive():
    snaps = ['- button "EXPLORE   the demo ledger"']
    assert unreached(["Explore the demo ledger", "Missing text"], snaps) == ["Missing text"]


def _failed(snapshot, output="E   AssertionError: Locator expected to be visible"):
    return RunResult("failed", output, snapshot)


def _unverified(*attempts):
    return VerificationResult("unverified", "the generated test failed against the PR build", None, list(attempts),
                              diagnosis="failed_on_head")


T = GeneratedTest("def test_x(page): ...", "x")


def test_change_never_rendered_is_reported_as_not_reachable():
    result = _unverified(Attempt(1, T, "failed_on_head", head=_failed("URL: /\n- heading \"Good morning\"")),
                         Attempt(2, T, "failed_on_head", head=_failed("URL: /\n- button \"Settings\"")))
    reason, diagnosis = explain(result, [change("  Explore the demo ledger")], '- heading "LIQUID.OS"')
    assert diagnosis == "not_reachable"
    assert reason.startswith("change not reachable in this build")
    assert "'Explore the demo ledger'" in reason
    assert "Not a flaky test" in reason


def test_change_that_rendered_but_test_failed_names_the_error():
    result = _unverified(Attempt(1, T, "failed_on_head", head=_failed('- button "Explore the demo ledger"')))
    reason, diagnosis = explain(result, [change("  Explore the demo ledger")], "- heading")
    assert diagnosis == "test_failed"
    assert "failed against the PR build after 1 attempt(s): AssertionError: Locator expected to be visible" in reason


def test_no_ui_text_in_diff_means_no_reachability_claim():
    result = _unverified(Attempt(1, T, "failed_on_head", head=_failed("- heading")))
    reason, diagnosis = explain(result, [change("  return `${value >= 0 ? '+' : ''}%`;")], "- heading")
    assert diagnosis == "test_failed"


def test_other_verdicts_pass_through():
    result = VerificationResult("unverified", "the generated test is not stable: x", None,
                                [Attempt(1, T, "unstable", stability=["x"])], diagnosis="unstable")
    assert explain(result, [], "") == ("the generated test is not stable: x", "unstable")
