import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "action"))
import gate  # noqa: E402

REPO = "hrithiknl17/liquid-financial"


def event(head_repo=REPO):
    return {"pull_request": {"number": 1, "head": {"repo": {"full_name": head_repo}}}}


def test_same_repo_pr_with_key_passes():
    assert gate.decide(event(), REPO, has_key=True) == (False, "")


def test_fork_pr_is_skipped_even_if_a_key_were_present():
    skip, reason = gate.decide(event("someone/liquid-financial"), REPO, has_key=True)
    assert skip and "Fork PR" in reason and "read-only token" in reason


def test_missing_key_is_skipped():
    skip, reason = gate.decide(event(), REPO, has_key=False)
    assert skip and "GEMINI_API_KEY" in reason


@pytest.mark.parametrize("payload", [{}, {"pull_request": None}, {"push": {}}])
def test_non_pr_events_are_skipped(payload):
    assert gate.decide(payload, REPO, has_key=True)[0]


def test_deleted_fork_head_repo_is_treated_as_fork():
    # GitHub sends head.repo = null when the fork was deleted.
    payload = {"pull_request": {"head": {"repo": None}}}
    assert gate.decide(payload, REPO, has_key=True)[0]


def run_gate(tmp_path, payload, has_key):
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(payload), encoding="utf-8")
    output, summary = tmp_path / "output", tmp_path / "summary"
    env = {**os.environ, "PRGEN_HAS_KEY": "true" if has_key else "false", "GITHUB_OUTPUT": str(output),
           "GITHUB_STEP_SUMMARY": str(summary)}
    subprocess.run([sys.executable, str(ROOT / "action" / "gate.py"), "--event", str(event_file),
                    "--repository", REPO], env=env, check=True, capture_output=True)
    return output.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8") if summary.exists() else ""


def test_script_writes_outputs_and_skip_summary(tmp_path):
    out, summary = run_gate(tmp_path, event("someone/fork"), has_key=True)
    assert out.startswith("skip=true\nreason=Fork PR")
    assert "PR test generation skipped" in summary


def test_script_pass_writes_no_summary(tmp_path):
    out, summary = run_gate(tmp_path, event(), has_key=True)
    assert out == "skip=false\nreason=\n"
    assert summary == ""


def test_gate_uses_only_the_standard_library():
    # It runs before `pip install`, so a third-party import would break every run.
    source = (ROOT / "action" / "gate.py").read_text(encoding="utf-8")
    imports = {line.split()[1].split(".")[0] for line in source.splitlines()
               if line.startswith(("import ", "from ")) and not line.startswith("from __future__")}
    assert imports <= {"argparse", "json", "os", "sys", "typing"}
