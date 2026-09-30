"""Run one generated test file with pytest-playwright against a served build."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TEST_FILENAME = "test_generated.py"
SNAPSHOT_FILENAME = "failure_snapshot.txt"
MAX_OUTPUT = 6000

# Only what Python, Chromium and temp files need. No tokens, no API keys: the
# code being run was written by a model reading untrusted PR content.
_ENV_KEEP = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    "XDG_CACHE_HOME", "PLAYWRIGHT_BROWSERS_PATH", "LANG", "LC_ALL",
)

# Captures what the page looked like when the test failed; that snapshot is
# the DOM the single retry gets to see.
CONFTEST = '''\
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _failfirst_fail_fast(page):
    page.set_default_timeout(10_000)
    # Stability checks re-run the test at other wall-clock times. A test that
    # pins its own clock overrides this, which is exactly what makes it stable.
    fixed = os.environ.get("FAILFIRST_FIXED_TIME")
    if fixed:
        page.clock.set_fixed_time(fixed)
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    page = item.funcargs.get("page")
    if page is None:
        return
    try:
        snap = page.locator("body").aria_snapshot(timeout=5_000)
    except Exception as exc:  # the page may be gone
        snap = f"(could not capture snapshot: {exc})"
    Path(__file__).with_name("%s").write_text(f"URL: {page.url}\\n{snap}", encoding="utf-8")
''' % SNAPSHOT_FILENAME


@dataclass(frozen=True)
class RunResult:
    outcome: str  # "passed" | "failed" | "error"
    output: str
    failure_snapshot: str = ""


def run_test(
    code: str, base_url: str, workdir: Path, *, timeout: int = 180, fixed_time: Optional[str] = None
) -> RunResult:
    """Run ``code`` against ``base_url``. ``fixed_time`` (ISO local time) fakes the browser clock."""
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (workdir / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (workdir / TEST_FILENAME).write_text(code, encoding="utf-8")
    snapshot_file = workdir / SNAPSHOT_FILENAME
    if snapshot_file.exists():
        snapshot_file.unlink()

    cmd = [
        sys.executable, "-m", "pytest", TEST_FILENAME,
        "-c", "pytest.ini", "--rootdir", ".", "-p", "no:cacheprovider",
        "--base-url", base_url, "--browser", "chromium", "-q", "--tb=short",
    ]
    try:
        env = _scrubbed_env()
        if fixed_time:
            env["FAILFIRST_FIXED_TIME"] = fixed_time
        proc = subprocess.run(
            cmd, cwd=str(workdir), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return RunResult("error", f"test run timed out after {timeout}s")

    output = (proc.stdout + proc.stderr)[-MAX_OUTPUT:]
    (workdir / "pytest-output.txt").write_text(output, encoding="utf-8")
    outcome = {0: "passed", 1: "failed"}.get(proc.returncode, "error")
    snapshot = snapshot_file.read_text(encoding="utf-8") if snapshot_file.exists() else ""
    return RunResult(outcome, output, snapshot)


def _scrubbed_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_KEEP}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
