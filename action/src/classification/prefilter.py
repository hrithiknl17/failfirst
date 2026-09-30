"""Rules that answer "no test needed" without an LLM call.

Conservative on purpose: a rule here may only cover files that cannot change
what a browser renders. Anything ambiguous — server code, SQL, config that
feeds the build — is left for the LLM, which costs one cheap call. Wrongly
skipping a real UI change is the one mistake this module must not make.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

from diff_extraction import FileChange
from diff_extraction.globs import first_match

SKIP_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # Root-level only: markdown under src/ or content/ may be rendered pages.
    ("documentation", ("*.md", "docs/**", "**/LICENSE*", "**/CHANGELOG*")),
    ("tests", ("tests/**", "test/**", "e2e/**", "**/__tests__/**", "**/*.test.*", "**/*.spec.*")),
    ("CI config", (".github/**", ".gitlab-ci.yml", ".circleci/**")),
    (
        "repo housekeeping",
        (".gitignore", "**/.gitattributes", ".editorconfig", ".prettierrc*", ".eslintrc*",
         ".env.example", ".vscode/**", ".claude/**"),
    ),
)


@dataclass(frozen=True)
class PrefilterResult:
    candidates: List[FileChange]  # need a real judgement
    skipped: List[Tuple[str, str]]  # (path, category)

    @property
    def needs_llm(self) -> bool:
        return bool(self.candidates)


def prefilter(
    files: Sequence[FileChange],
    rules: Sequence[Tuple[str, Sequence[str]]] = SKIP_RULES,
) -> PrefilterResult:
    candidates: List[FileChange] = []
    skipped: List[Tuple[str, str]] = []
    for change in files:
        category = _category(change.path, rules)
        if category:
            skipped.append((change.path, category))
        else:
            candidates.append(change)
    return PrefilterResult(candidates=candidates, skipped=skipped)


def _category(path: str, rules: Sequence[Tuple[str, Sequence[str]]]) -> str:
    for category, patterns in rules:
        if first_match(path, patterns):
            return category
    return ""
