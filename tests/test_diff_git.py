"""extract_diff against a real throwaway git repo."""
import subprocess

import pytest

from diff_extraction import DiffError, extract_diff


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Header.tsx").write_text("export const title = 'Old';\n")
    (tmp_path / "package-lock.json").write_text('{"v": 1}\n')
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")

    git(tmp_path, "checkout", "-q", "-b", "feature")
    (tmp_path / "src" / "Header.tsx").write_text("export const title = 'New';\n")
    (tmp_path / "src" / "Footer.tsx").write_text("export const footer = 'hi';\n")
    (tmp_path / "package-lock.json").write_text('{"v": 2}\n')
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "feature work")
    return tmp_path


def test_extracts_feature_branch_changes(repo):
    result = extract_diff(str(repo), "main", "feature")
    assert {(c.path, c.status) for c in result.files} == {
        ("src/Header.tsx", "modified"),
        ("src/Footer.tsx", "added"),
    }
    assert [p for p, _ in result.dropped] == ["package-lock.json"]


def test_three_dot_ignores_commits_made_on_base_after_branching(repo):
    git(repo, "checkout", "-q", "main")
    (repo / "later-on-main.md").write_text("not part of the PR\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "main moves on")

    result = extract_diff(str(repo), "main", "feature")
    assert "later-on-main.md" not in {c.path for c in result.files}


def test_bad_ref_raises(repo):
    with pytest.raises(DiffError, match="no-such-branch"):
        extract_diff(str(repo), "main", "no-such-branch")
