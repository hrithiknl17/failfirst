"""Static check of generated test code before it is executed.

The code comes from an LLM whose input includes untrusted PR content, and it
runs on the CI runner. So it may only import the test toolkit, and it may only
drive the browser the way a user would: no script injection, no request
interception, no reaching outside the app. These double as honesty rules — a
test can't pass by rewriting the page it is checking.
"""
from __future__ import annotations

import ast
from typing import List

ALLOWED_IMPORTS = frozenset({"re", "pytest", "playwright.sync_api"})

FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "getattr", "setattr", "delattr",
    "globals", "locals", "vars", "input", "breakpoint", "__builtins__",
})

FORBIDDEN_ATTRS = frozenset({
    # JS execution / page rewriting
    "evaluate", "evaluate_handle", "eval_on_selector", "eval_on_selector_all",
    "add_init_script", "add_script_tag", "add_style_tag", "set_content", "dispatch_event",
    "expose_function", "expose_binding",
    # network interception / out-of-band requests
    "route", "route_from_har", "unroute", "request", "set_extra_http_headers",
    # state injection (reach state through the UI instead)
    "add_cookies", "storage_state", "clear_cookies",
    # fixed sleeps make tests flaky; expect() already waits
    "wait_for_timeout",
})


def check_test_code(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}: {exc.msg}"]

    problems: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_IMPORTS:
                    problems.append(f"import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_IMPORTS:
                problems.append(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            problems.append(f"use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__"):
                problems.append(f"dunder attribute '{node.attr}' is not allowed")
            elif node.attr in FORBIDDEN_ATTRS:
                problems.append(f"'.{node.attr}' is not allowed: interact only as a user would")
        elif isinstance(node, ast.Call):
            problem = _check_goto(node)
            if problem:
                problems.append(problem)

    if not any(isinstance(n, ast.FunctionDef) and n.name.startswith("test_") for n in tree.body):
        problems.append("no top-level test_ function")
    return list(dict.fromkeys(problems))


def _check_goto(call: ast.Call) -> str:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr == "goto"):
        return ""
    target = call.args[0] if call.args else None
    if not (isinstance(target, ast.Constant) and isinstance(target.value, str) and target.value.startswith("/")):
        return "page.goto() must use a literal app-relative path such as \"/\""
    return ""
