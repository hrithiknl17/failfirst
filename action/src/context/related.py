"""Source-level context read from the PR commit via git.

Everything here reads ``<sha>:<path>`` through git, never the working tree, so
it describes exactly the commit being tested.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Sequence, Set

from diff_extraction import FileChange

SOURCE_EXTS = ("*.ts", "*.tsx", "*.js", "*.jsx", "*.vue", "*.svelte")
TEST_PATHSPECS = ("*.test.*", "*.spec.*", "e2e/*", "tests/*")
MAX_SOURCE_LINES = 400
MAX_USAGES_PER_SYMBOL = 15
MAX_TEST_FILES = 2
MAX_TEST_LINES = 150

# Top-level declarations in JS/TS: the unit a user-visible change hangs off.
_EXPORT = re.compile(
    r"^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)"
)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


@dataclass(frozen=True)
class Usage:
    symbol: str
    path: str
    line: int
    text: str


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def file_at(repo: str, sha: str, path: str) -> str:
    proc = _git(repo, "show", f"{sha}:{path}")
    return proc.stdout if proc.returncode == 0 else ""


def head_sources(repo: str, sha: str, changes: Sequence[FileChange]) -> Dict[str, str]:
    """New content of each changed text file (capped), so the model sees whole components."""
    out: Dict[str, str] = {}
    for change in changes:
        if change.status == "deleted" or change.binary:
            continue
        text = file_at(repo, sha, change.path)
        lines = text.splitlines()
        if len(lines) > MAX_SOURCE_LINES:
            text = "\n".join(lines[:MAX_SOURCE_LINES]) + "\n[... file truncated]"
        if text:
            out[change.path] = text
    return out


def changed_lines(patch: str) -> List[int]:
    """New-file line numbers touched by a patch (a pure deletion maps to where it happened)."""
    touched: List[int] = []
    new_line = 0
    for line in patch.split("\n"):
        header = _HUNK.match(line)
        if header:
            new_line = int(header.group(1))
            continue
        if line.startswith("+"):
            touched.append(new_line)
            new_line += 1
        elif line.startswith("-"):
            touched.append(new_line)
        elif line.startswith("\\"):
            continue
        else:
            new_line += 1
    return touched


def changed_symbols(source: str, patch: str) -> List[str]:
    """Exported declarations whose bodies contain a changed line."""
    lines = source.splitlines()
    names: List[str] = []
    for number in changed_lines(patch):
        for index in range(min(number, len(lines)) - 1, -1, -1):
            found = _EXPORT.match(lines[index])
            if found:
                if found.group(1) not in names:
                    names.append(found.group(1))
                break
    return names


def usages(repo: str, sha: str, symbol: str, exclude_path: str) -> List[Usage]:
    proc = _git(repo, "grep", "-n", "-w", "-I", "-e", symbol, sha, "--", *SOURCE_EXTS)
    found: List[Usage] = []
    for raw in proc.stdout.splitlines():
        # Format: <sha>:<path>:<line>:<text>
        parts = raw.split(":", 3)
        if len(parts) != 4 or parts[1] == exclude_path:
            continue
        found.append(Usage(symbol, parts[1], int(parts[2]), parts[3].strip()[:200]))
        if len(found) >= MAX_USAGES_PER_SYMBOL:
            break
    return found


def symbol_usages(repo: str, sha: str, changes: Sequence[FileChange], sources: Dict[str, str]) -> List[Usage]:
    out: List[Usage] = []
    for change in changes:
        source = sources.get(change.path)
        if not source or not change.patch:
            continue
        for symbol in changed_symbols(source, change.patch):
            out.extend(usages(repo, sha, symbol, change.path))
    return out


def related_tests(repo: str, sha: str, changes: Sequence[FileChange]) -> Dict[str, str]:
    """Existing tests that mention a changed file's module name, for style and fixtures."""
    stems: Set[str] = {c.path.rsplit("/", 1)[-1].split(".", 1)[0] for c in changes}
    out: Dict[str, str] = {}
    for stem in sorted(s for s in stems if len(s) >= 3):
        proc = _git(repo, "grep", "-l", "-w", "-I", "-e", stem, sha, "--", *TEST_PATHSPECS)
        for raw in proc.stdout.splitlines():
            path = raw.split(":", 1)[1] if ":" in raw else raw
            if path in out:
                continue
            lines = file_at(repo, sha, path).splitlines()[:MAX_TEST_LINES]
            out[path] = "\n".join(lines)
            if len(out) >= MAX_TEST_FILES:
                return out
    return out
