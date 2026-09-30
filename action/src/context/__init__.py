"""Gather what generation needs to write a grounded test.

- existing tests that touch the changed files, so style and fixtures match
- new source of changed files and call sites of changed exported symbols
- an ARIA snapshot captured from the PR's build running locally — the only
  selectors generation is allowed to use besides text in the new source
"""
from dataclasses import dataclass
from typing import Dict, List

from .related import Usage, head_sources, related_tests, symbol_usages
from .snapshot import capture_aria_snapshot
from .worktree import (
    DEFAULT_BUILD_CMD,
    DEFAULT_INSTALL_CMD,
    DEFAULT_SERVE_CMD,
    BuildError,
    build,
    checkout,
    merge_base,
    resolve_sha,
    serve,
)


@dataclass(frozen=True)
class GenerationContext:
    sources: Dict[str, str]
    usages: List[Usage]
    existing_tests: Dict[str, str]
    aria_snapshot: str
    notes: str = ""  # optional per-repo hints for the model


def gather(repo: str, head_sha: str, changes, head_url: str, notes: str = "") -> GenerationContext:
    sources = head_sources(repo, head_sha, changes)
    return GenerationContext(
        sources=sources,
        usages=symbol_usages(repo, head_sha, changes, sources),
        existing_tests=related_tests(repo, head_sha, changes),
        aria_snapshot=capture_aria_snapshot(head_url),
        notes=notes,
    )


__all__ = [
    "DEFAULT_BUILD_CMD",
    "DEFAULT_INSTALL_CMD",
    "DEFAULT_SERVE_CMD",
    "BuildError",
    "GenerationContext",
    "Usage",
    "build",
    "capture_aria_snapshot",
    "checkout",
    "gather",
    "head_sources",
    "merge_base",
    "related_tests",
    "resolve_sha",
    "serve",
    "symbol_usages",
]
