import pytest

from diff_extraction.globs import first_match, match


@pytest.mark.parametrize(
    "path, pattern, expected",
    [
        ("README.md", "*.md", True),
        ("src/content/page.md", "*.md", False),  # * must not cross "/"
        ("src/content/page.md", "**/*.md", True),
        ("package-lock.json", "**/package-lock.json", True),
        ("apps/web/package-lock.json", "**/package-lock.json", True),
        ("dist/assets/index.js", "dist/**", True),
        ("src/dist/index.js", "dist/**", False),
        ("src/App.test.tsx", "**/*.test.*", True),
        ("src/Attest.tsx", "**/*.test.*", False),
        (".github/workflows/ci.yml", ".github/**", True),
        ("a/b", "a?b", False),  # ? must not match "/"
    ],
)
def test_match(path, pattern, expected):
    assert match(path, pattern) is expected


def test_first_match_returns_the_matching_pattern():
    assert first_match("docs/x.md", ["*.txt", "docs/**"]) == "docs/**"
    assert first_match("src/x.tsx", ["*.txt", "docs/**"]) is None
