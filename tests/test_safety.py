import pytest

from generation import check_test_code

GOOD = '''\
import re
import pytest
from playwright.sync_api import Page, expect


def test_label(page: Page):
    """New label is shown."""
    page.goto("/")
    page.get_by_role("button", name=re.compile("Add", re.I)).click()
    expect(page.get_by_text("Add today's spend")).to_be_visible()
'''


def test_user_like_test_passes():
    assert check_test_code(GOOD) == []


@pytest.mark.parametrize("snippet, expected", [
    ("import os", "import of 'os'"),
    ("import subprocess", "import of 'subprocess'"),
    ("from pathlib import Path", "import from 'pathlib'"),
    ("from . import x", "import from 'None'"),
    ("x = open('/etc/passwd')", "use of 'open'"),
    ("x = eval('1')", "use of 'eval'"),
    ("x = __import__('os')", "use of '__import__'"),
    ("x = ().__class__", "dunder attribute '__class__'"),
])
def test_escapes_from_the_sandbox_are_rejected(snippet, expected):
    problems = check_test_code(snippet + "\n\ndef test_x(page):\n    pass\n")
    assert any(expected in p for p in problems), problems


@pytest.mark.parametrize("call", [
    "page.evaluate('document.body.innerHTML = \"x\"')",
    "page.add_init_script('localStorage.x = 1')",
    "page.route('**/*', lambda r: r.abort())",
    "page.set_content('<button>Add</button>')",
    "page.request.get('https://example.com')",
    "page.context.add_cookies([])",
    "page.wait_for_timeout(1000)",
])
def test_non_user_actions_are_rejected(call):
    problems = check_test_code(f"def test_x(page):\n    {call}\n")
    assert any("not allowed" in p for p in problems), problems


@pytest.mark.parametrize("target", ['"https://evil.example"', "url", '"relative"'])
def test_goto_must_be_literal_app_path(target):
    problems = check_test_code(f"def test_x(page):\n    page.goto({target})\n")
    assert any("page.goto()" in p for p in problems)


def test_syntax_error_and_missing_test_function():
    assert check_test_code("def test_x(:\n")[0].startswith("syntax error")
    assert check_test_code("def helper(page):\n    pass\n") == ["no top-level test_ function"]
