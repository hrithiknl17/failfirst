import pytest

from classification import AffectedArea, Classification
from context import GenerationContext, Usage
from context.related import changed_lines, changed_symbols
from diff_extraction import FileChange
from generation import Feedback, GenerationError, build_prompt, generate_test
from llm import LLMError

CLS = Classification(
    user_facing=True, confidence="high", reason="Button label changes.", decided_by="llm",
    affected_areas=[AffectedArea("Label", ["src/Signals.tsx"], "Hub brief banner")],
    test_idea="Check the new label.",
)
CHANGE = FileChange("src/Signals.tsx", "modified", "@@ -71 +71 @@\n-  Log a spend\n+  Add today's spend", 1, 1)
CTX = GenerationContext(
    sources={"src/Signals.tsx": "export const BriefBanner = () => <button>Add today's spend</button>;"},
    usages=[Usage("BriefBanner", "src/components/HubScreen.tsx", 12, "<BriefBanner />")],
    existing_tests={},
    aria_snapshot='- button "Add today\'s spend"',
)


class FakeLLM:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def test_prompt_has_classifier_summary_diff_source_usages_and_snapshot():
    prompt = build_prompt(CLS, [CHANGE], CTX)
    for expected in ["Button label changes.", "Hub brief banner", "+  Add today's spend",
                     "BEGIN FILE: src/Signals.tsx", "src/components/HubScreen.tsx:12 (BriefBanner)",
                     '- button "Add today\'s spend"', "BEGIN UNTRUSTED PR CONTENT"]:
        assert expected in prompt
    # The real snapshot is outside the untrusted block: it came from our own browser.
    assert prompt.index("END UNTRUSTED PR CONTENT") < prompt.index("ARIA snapshot")


def test_retry_prompt_carries_failure_evidence():
    fb = Feedback("def test_old(page): ...", "failed_on_head", "E  element(s) not found", "URL: /\n- button \"X\"")
    prompt = build_prompt(CLS, [CHANGE], CTX, fb)
    assert "FAILED against the PR build" in prompt
    assert "element(s) not found" in prompt
    assert 'button "X"' in prompt
    assert "def test_old" in prompt


def test_passed_on_base_feedback_explains_the_problem():
    prompt = build_prompt(CLS, [CHANGE], CTX, Feedback("code", "passed_on_base"))
    assert "does not check the change" in prompt


def test_generate_strips_markdown_fences():
    llm = FakeLLM({"what_it_checks": "label", "test_code": "```python\ndef test_x(page):\n    pass\n```"})
    test = generate_test(CLS, [CHANGE], CTX, llm, model="m")
    assert test.code == "def test_x(page):\n    pass\n"
    assert test.what_it_checks == "label"


def test_generate_errors_surface():
    with pytest.raises(GenerationError, match="empty"):
        generate_test(CLS, [CHANGE], CTX, FakeLLM({"what_it_checks": "", "test_code": " "}), model="m")
    with pytest.raises(GenerationError, match="down"):
        generate_test(CLS, [CHANGE], CTX, FakeLLM(error=LLMError("down")), model="m")


# --- context.related: which exported symbols a patch touched ------------

SOURCE = """\
import x from 'y';

export function money(v) {
  return v.toFixed(2);
}

export function percent(value, decimals = 0) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;
}
"""
PATCH = "\n".join([
    "@@ -6,4 +6,4 @@ export function money(v) {",
    " ",
    " export function percent(value, decimals = 0) {",
    "-  return `${value > 0 ? '+' : ''}${value.toFixed(decimals)}%`;",
    "+  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`;",
    " }",
])


def test_changed_lines_maps_to_new_file_line_numbers():
    assert changed_lines(PATCH) == [8, 8]


def test_changed_symbols_finds_enclosing_export_not_hunk_header():
    # git's hunk header names `money`, but the change is inside `percent`.
    assert changed_symbols(SOURCE, PATCH) == ["percent"]
