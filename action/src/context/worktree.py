"""Check out, build and serve one ref of the target repo.

Each ref gets a git worktree at ``<repo>/.prgen/worktrees/<sha>``. Nesting it
inside the checkout means Node finds the checkout's ``node_modules`` by walking
up, so most builds need no install. Worktrees are keyed by commit SHA, so a
rerun reuses a finished build.
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List

import httpx

WORKTREE_DIR = Path(".prgen") / "worktrees"
BUILT_MARKER = ".prgen-built"

DEFAULT_BUILD_CMD = "npm run build"
DEFAULT_SERVE_CMD = "npm run preview -- --port {port} --strictPort --host 127.0.0.1"
DEFAULT_INSTALL_CMD = "npm ci --no-audit --no-fund"


class BuildError(RuntimeError):
    """The target app could not be checked out, installed, built or served."""


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def resolve_sha(repo: str, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def merge_base(repo: str, base: str, head: str) -> str:
    return git(repo, "merge-base", base, head).strip()


def checkout(repo: str, sha: str) -> Path:
    _exclude_worktree_dir(repo)
    path = Path(repo).resolve() / WORKTREE_DIR / sha[:12]
    if (path / ".git").exists():
        return path
    git(repo, "worktree", "prune")
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--detach", "--force", str(path), sha)
    return path


def build(repo: str, worktree: Path, *, build_cmd: str = DEFAULT_BUILD_CMD,
          install_cmd: str = DEFAULT_INSTALL_CMD, timeout: int = 900) -> None:
    if (worktree / BUILT_MARKER).exists():
        return
    if _needs_install(Path(repo).resolve(), worktree):
        _run(install_cmd, worktree, timeout, "install")
    _run(build_cmd, worktree, timeout, "build")
    (worktree / BUILT_MARKER).write_text("ok\n")


@contextmanager
def serve(worktree: Path, *, serve_cmd: str = DEFAULT_SERVE_CMD, ready_timeout: float = 60.0) -> Iterator[str]:
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    log = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        _argv(serve_cmd.format(port=port)), cwd=str(worktree),
        stdout=log, stderr=subprocess.STDOUT, **_new_process_group(),
    )
    try:
        _wait_until_ready(url, proc, log, ready_timeout)
        yield url
    finally:
        _kill_tree(proc)
        log.close()


def _needs_install(repo_root: Path, worktree: Path) -> bool:
    if not (worktree / "package.json").exists():
        return False
    if not (repo_root / "node_modules").is_dir():
        return True
    for name in ("package.json", "package-lock.json"):
        a, b = repo_root / name, worktree / name
        if a.exists() != b.exists() or (a.exists() and a.read_bytes() != b.read_bytes()):
            return True
    return False


def _run(command: str, cwd: Path, timeout: int, what: str) -> None:
    try:
        proc = subprocess.run(
            _argv(command), cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"{what} timed out after {timeout}s: {command}") from exc
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-3000:]
        raise BuildError(f"{what} failed ({command}), exit {proc.returncode}:\n{tail}")


def _argv(command: str) -> List[str]:
    argv = shlex.split(command)
    exe = shutil.which(argv[0])  # finds npm.cmd on Windows
    if exe:
        argv[0] = exe
    return argv


def _exclude_worktree_dir(repo: str) -> None:
    common = Path(git(repo, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = Path(repo).resolve() / common
    exclude = common / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if ".prgen/" not in existing.splitlines():
        with exclude.open("a", encoding="utf-8") as fh:
            fh.write(("" if existing.endswith("\n") or not existing else "\n") + ".prgen/\n")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(url: str, proc: subprocess.Popen, log, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise BuildError(f"server exited with code {proc.returncode}:\n{_tail(log)}")
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise BuildError(f"server not ready at {url} after {timeout:.0f}s:\n{_tail(log)}")


def _tail(log, size: int = 2000) -> str:
    log.seek(0)
    return log.read().decode("utf-8", "replace")[-size:]


def _new_process_group() -> dict:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    # npm spawns node spawns vite: killing only npm would orphan the server.
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
