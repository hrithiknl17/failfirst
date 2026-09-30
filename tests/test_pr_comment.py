import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from pr_comment import MARKER, GitHubCommenter, fence, new_file_patch, plan_upsert, render_comment, safe_text

ROOT = Path(__file__).resolve().parents[1]
CODE = 'from playwright.sync_api import Page, expect\n\n\ndef test_x(page: Page):\n    page.goto("/")\n'

VERIFIED = {
    "status": "verified",
    "head": "demo/percent-zero",
    "classification": {"reason": "percent() now shows +0% for zero."},
    "verification": {
        "status": "verified",
        "reason": "passes on the PR build and fails on the base build, and held through 8 stability checks "
                  "(2 reruns, clock at 03:00, 13:00, 22:00)",
        "test": {"code": CODE, "what_it_checks": "zero shows +0%"},
        "attempts": [{"number": 1, "verdict": "verified"}],
    },
}
UNVERIFIED = {
    "status": "unverified",
    "head": "demo/ui-demo-button",
    "classification": {"reason": "Sign-in button label changed."},
    "verification": {
        "status": "unverified",
        "reason": "change not reachable in this build: none of the new UI text ('Explore the demo ledger') appeared",
        "test": {"code": "def test_secret_code(page): pass", "what_it_checks": "x"},
        "attempts": [{"number": 1, "verdict": "failed_on_head"}, {"number": 2, "verdict": "failed_on_head"}],
    },
}


# --- rendering ---------------------------------------------------------------

def test_verified_comment_has_badge_evidence_code_and_patch():
    body = render_comment(VERIFIED, test_repo_path="e2e/test_failfirst_demo_percent_zero.py")
    assert body.startswith(MARKER)
    assert "✅ Playwright test — VERIFIED" in body
    assert "fails, as it should" in body
    assert "held through 8 stability checks" in body
    assert "```python\n" + CODE.rstrip() in body
    assert "+++ b/e2e/test_failfirst_demo_percent_zero.py" in body


def test_unverified_comment_explains_and_never_shows_code():
    body = render_comment(UNVERIFIED)
    assert "UNVERIFIED (not posted)" in body
    assert "change not reachable in this build" in body
    assert "Attempt 2: failed on the PR build" in body
    assert "test_secret_code" not in body
    assert "```" not in body


def test_no_test_and_error_comments():
    body = render_comment({"status": "no_test_needed", "classification": {"reason": "Only docs changed."}})
    assert "No UI test needed" in body and "Only docs changed." in body
    body = render_comment({"status": "error", "error": "build failed"})
    assert "could not finish" in body and "No test was posted." in body


def test_llm_text_cannot_ping_people_or_inject_html():
    text = safe_text("ping @octocat and <img src=x onerror=alert(1)>")
    assert "@octocat" not in text and "@​octocat" in text
    assert "<img" not in text and "&lt;img" in text


def test_code_cannot_break_out_of_its_fence():
    tricky = 'x = """\n```\n## injected heading\n"""'
    fenced = fence(tricky, "python")
    assert fenced.startswith("````python\n") and fenced.endswith("\n````")


def test_patch_applies_with_git(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "failfirst.patch").write_text(new_file_patch("e2e/test_failfirst_x.py", CODE), encoding="utf-8")
    subprocess.run(["git", "apply", "failfirst.patch"], cwd=tmp_path, check=True)
    assert (tmp_path / "e2e" / "test_failfirst_x.py").read_text(encoding="utf-8") == CODE


# --- delivery: dry run makes no network calls --------------------------------

@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network call attempted during dry run")

    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx, "request", refuse)


def test_plan_upsert_describes_but_sends_nothing(no_network):
    plan = plan_upsert("owner/repo", 7, "body")
    assert plan["dry_run"] is True
    assert plan["create"]["url"] == "https://api.github.com/repos/owner/repo/issues/7/comments"
    assert "No request was sent" in plan["note"]


def test_cli_post_without_flag_is_a_dry_run(tmp_path, no_network, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-be-used")
    result = tmp_path / "result.json"
    result.write_text(json.dumps(VERIFIED), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "action"))
    import cli

    assert cli.main(["post", "--result", str(result), "--repo", "owner/repo", "--pr", "7"]) == 0
    assert "DRY RUN - nothing sent to GitHub" in capsys.readouterr().out
    plan = json.loads((tmp_path / "comment_request.json").read_text(encoding="utf-8"))
    assert plan["create"]["json"]["body"].startswith(MARKER)
    assert (tmp_path / "comment.md").read_text(encoding="utf-8").startswith(MARKER)


# --- real client, against a fake GitHub ----------------------------------------

def fake_github(existing_comments):
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=existing_comments)
        return httpx.Response(201 if request.method == "POST" else 200, json={"html_url": "https://gh/c/1"})

    return httpx.MockTransport(handler), calls


def test_creates_comment_when_none_exists():
    transport, calls = fake_github([{"id": 5, "body": "unrelated"}])
    url = GitHubCommenter("t", "o/r", 3, transport=transport).upsert(MARKER + " hi")
    assert url == "https://gh/c/1"
    assert calls[-1] == ("POST", "/repos/o/r/issues/3/comments")


def test_updates_previous_failfirst_comment_instead_of_spamming():
    transport, calls = fake_github([{"id": 42, "body": MARKER + " old"}])
    GitHubCommenter("t", "o/r", 3, transport=transport).upsert(MARKER + " new")
    assert calls[-1] == ("PATCH", "/repos/o/r/issues/comments/42")


def test_posting_requires_a_token():
    with pytest.raises(Exception, match="GITHUB_TOKEN"):
        GitHubCommenter("", "o/r", 3)
