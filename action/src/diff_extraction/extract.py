"""Pull a PR's diff out of git, parse it per file, and drop pure noise.

Reads ``git diff base...head`` (three dots: only what the PR branch added since
it forked from base), so the same code runs against the local sandbox clone and
inside the Action after ``actions/checkout`` with ``fetch-depth: 0``.

"Noise" means files that never carry reviewable intent — lockfiles and build
output. Deciding what is *user-facing* is classification's job, not this one's.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field, replace
from typing import List, Optional, Sequence, Tuple

from .globs import first_match

NOISE_PATTERNS: Tuple[str, ...] = (
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/poetry.lock",
    "**/Pipfile.lock",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "dist/**",
    "build/**",
)

# Enough for a model to judge a change without paying for a thousand-line
# generated file. Files past the total budget are still listed, patch-less.
MAX_LINES_PER_FILE = 400
MAX_TOTAL_LINES = 3000


class DiffError(RuntimeError):
    """git could not produce or we could not parse the diff."""


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # added | modified | deleted | renamed
    patch: str = ""  # hunks only (from the first "@@"); file headers stripped
    old_path: Optional[str] = None  # set only for renames
    added: int = 0
    removed: int = 0
    binary: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class DiffResult:
    base: str
    head: str
    files: List[FileChange]
    dropped: List[Tuple[str, str]] = field(default_factory=list)  # (path, reason)


def extract_diff(
    repo: str,
    base: str,
    head: str,
    *,
    noise_patterns: Sequence[str] = NOISE_PATTERNS,
    max_lines_per_file: int = MAX_LINES_PER_FILE,
    max_total_lines: int = MAX_TOTAL_LINES,
) -> DiffResult:
    raw = run_git_diff(repo, base, head)
    kept, dropped = filter_changes(
        parse_unified_diff(raw),
        noise_patterns=noise_patterns,
        max_lines_per_file=max_lines_per_file,
        max_total_lines=max_total_lines,
    )
    return DiffResult(base=base, head=head, files=kept, dropped=dropped)


def run_git_diff(repo: str, base: str, head: str) -> str:
    cmd = [
        "git", "-C", repo, "-c", "core.quotepath=false",
        "diff", "--no-color", "--no-ext-diff", "--find-renames", "-U3",
        f"{base}...{head}",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
        )
    except FileNotFoundError as exc:
        raise DiffError("git is not installed or not on PATH") from exc
    if proc.returncode != 0:
        raise DiffError(f"git diff {base}...{head} failed: {proc.stderr.strip()}")
    return proc.stdout


def parse_unified_diff(text: str) -> List[FileChange]:
    return [_parse_block(block) for block in _split_blocks(text)]


def filter_changes(
    files: Sequence[FileChange],
    *,
    noise_patterns: Sequence[str] = NOISE_PATTERNS,
    max_lines_per_file: int = MAX_LINES_PER_FILE,
    max_total_lines: int = MAX_TOTAL_LINES,
) -> Tuple[List[FileChange], List[Tuple[str, str]]]:
    kept: List[FileChange] = []
    dropped: List[Tuple[str, str]] = []
    budget = max_total_lines
    for change in files:
        rule = first_match(change.path, noise_patterns)
        if rule:
            dropped.append((change.path, f"noise: matches {rule}"))
            continue
        change = _trim(change, max(0, min(max_lines_per_file, budget)))
        if change.patch:
            budget -= len(change.patch.split("\n"))
        kept.append(change)
    return kept, dropped


def _trim(change: FileChange, limit: int) -> FileChange:
    if not change.patch:
        return change
    lines = change.patch.split("\n")
    if len(lines) <= limit:
        return change
    return replace(change, patch="\n".join(lines[:limit]), truncated=True)


def _split_blocks(text: str) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current is not None:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")


def _parse_block(lines: List[str]) -> FileChange:
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    header = _HEADER.match(lines[0])
    if header:
        old_path, new_path = header.group(1), header.group(2)

    status = "modified"
    binary = False
    hunk_start: Optional[int] = None
    for i, line in enumerate(lines[1:], start=1):
        if line.startswith("@@"):
            hunk_start = i
            break
        if line.startswith("new file mode"):
            status = "added"
        elif line.startswith("deleted file mode"):
            status = "deleted"
        elif line.startswith("rename from "):
            old_path, status = _unquote(line[len("rename from "):]), "renamed"
        elif line.startswith("rename to "):
            new_path, status = _unquote(line[len("rename to "):]), "renamed"
        elif line.startswith("Binary files ") or line == "GIT binary patch":
            binary = True
        elif line.startswith("--- "):
            old_path = _marker_path(line[4:], "a/") or old_path
        elif line.startswith("+++ "):
            new_path = _marker_path(line[4:], "b/") or new_path

    path = old_path if status == "deleted" else new_path
    if not path:
        raise DiffError(f"could not work out the file path for: {lines[0]!r}")

    hunks = lines[hunk_start:] if hunk_start is not None else []
    return FileChange(
        path=path,
        status=status,
        patch="\n".join(hunks),
        old_path=old_path if status == "renamed" else None,
        added=sum(1 for line in hunks if line.startswith("+")),
        removed=sum(1 for line in hunks if line.startswith("-")),
        binary=binary,
    )


def _marker_path(value: str, prefix: str) -> Optional[str]:
    value = value.rstrip("\t")
    if value == "/dev/null":
        return None
    value = _unquote(value)
    return value[len(prefix):] if value.startswith(prefix) else value


def _unquote(value: str) -> str:
    # With core.quotepath=false git only quotes paths containing ", \, tab or
    # newline, using C-style escapes.
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1].replace('\\"', '"').replace("\\t", "\t").replace("\\\\", "\\")
    return value
