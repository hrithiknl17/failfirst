"""Security properties of the Action and the example workflow, checked statically."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ACTION = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
EXAMPLE_TEXT = (ROOT / "examples" / "liquid-financial" / "failfirst.yml").read_text(encoding="utf-8")
EXAMPLE = yaml.safe_load(EXAMPLE_TEXT)
STEPS = ACTION["runs"]["steps"]


def triggers(workflow):
    # PyYAML reads the bare key `on` as boolean True.
    return workflow.get("on", workflow.get(True))


def step(name):
    return next(s for s in STEPS if s.get("name") == name)


def test_example_triggers_on_pull_request_only():
    assert set(triggers(EXAMPLE)) == {"pull_request"}
    assert not re.search(r"^\s*pull_request_target\s*:", EXAMPLE_TEXT, re.MULTILINE)


def test_example_permissions_are_minimal():
    assert EXAMPLE["permissions"] == {"contents": "read", "pull-requests": "write"}


def test_example_checkout_leaves_no_credentials_and_fetches_history():
    checkout = next(s for s in EXAMPLE["jobs"]["failfirst"]["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha }}"


def test_gate_is_first_and_everything_else_depends_on_it():
    assert STEPS[0]["id"] == "gate"
    for s in STEPS[1:]:
        assert "steps.gate.outputs.skip == 'false'" in s.get("if", ""), s["name"]


def test_no_pr_controlled_text_is_interpolated_into_shell():
    # ${{ github.event.pull_request.title }} (or body, head.ref...) inside run: is script injection.
    for s in STEPS:
        assert "github.event" not in s.get("run", ""), s["name"]
        assert "${{" not in s.get("run", ""), s["name"]


def test_secrets_only_reach_the_steps_that_need_them():
    holders = {s["name"] for s in STEPS if "gemini-api-key" in str(s.get("env", {}))}
    assert holders == {"Gate", "Generate and verify test"}
    # The gate only learns *whether* a key exists, never its value.
    assert step("Gate")["env"] == {"FAILFIRST_HAS_KEY": "${{ inputs.gemini-api-key != '' }}"}
    token_holders = {s["name"] for s in STEPS if "github-token" in str(s.get("env", {}))}
    assert token_holders == {"Post PR comment"}
    assert "gemini" not in str(step("Install app dependencies").get("env", {})).lower()


def test_only_the_post_step_uses_the_post_flag():
    posting = [s["name"] for s in STEPS if "--post" in s.get("run", "")]
    assert posting == ["Post PR comment"]
    assert "inputs.post-comment == 'true'" in step("Post PR comment")["if"]
    assert "inputs.post-comment != 'true'" in step("Render PR comment (dry run, nothing sent)")["if"]


@pytest.mark.parametrize("path", ["action.yml", "examples/liquid-financial/failfirst.yml", ".github/workflows/ci.yml"])
def test_third_party_actions_are_first_party_github_only(path):
    uses = re.findall(r"uses:\s*([^\s#]+)", (ROOT / path).read_text(encoding="utf-8"))
    for ref in uses:
        assert ref.startswith("actions/") or ref.startswith("OWNER/failfirst@"), ref
