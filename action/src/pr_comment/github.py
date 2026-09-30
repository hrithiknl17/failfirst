"""Deliver the comment: dry-run plan by default, real GitHub calls only on request.

``plan_upsert`` is pure — it describes the requests that *would* be made and
touches no network. ``GitHubCommenter`` makes real API calls and is only
constructed when a caller explicitly asks to post.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .render import MARKER

API = "https://api.github.com"


class PostError(RuntimeError):
    """GitHub refused or failed the request."""


def plan_upsert(repo: str, pr: int, body: str) -> Dict[str, Any]:
    """The request a real post would make. Written to disk in dry-run mode."""
    return {
        "dry_run": True,
        "note": (
            f"Would list comments on {repo}#{pr}, update the one containing {MARKER!r} if present, "
            "otherwise create a new comment. No request was sent."
        ),
        "create": {"method": "POST", "url": f"{API}/repos/{repo}/issues/{pr}/comments", "json": {"body": body}},
        "update": {"method": "PATCH", "url": f"{API}/repos/{repo}/issues/comments/<existing id>", "json": {"body": body}},
    }


class GitHubCommenter:
    def __init__(self, token: str, repo: str, pr: int, *, transport: Optional[httpx.BaseTransport] = None) -> None:
        if not token:
            raise PostError("GITHUB_TOKEN is required to post")
        self._repo, self._pr = repo, pr
        self._http = httpx.Client(
            base_url=API,
            transport=transport,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def upsert(self, body: str) -> str:
        """Update our previous comment on the PR (found by marker) or create one. Returns its URL."""
        existing = self._find_existing()
        if existing is not None:
            resp = self._http.patch(f"/repos/{self._repo}/issues/comments/{existing}", json={"body": body})
        else:
            resp = self._http.post(f"/repos/{self._repo}/issues/{self._pr}/comments", json={"body": body})
        if resp.status_code not in (200, 201):
            raise PostError(f"GitHub returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("html_url", "")

    def _find_existing(self) -> Optional[int]:
        page = 1
        while True:
            resp = self._http.get(
                f"/repos/{self._repo}/issues/{self._pr}/comments", params={"per_page": 100, "page": page}
            )
            if resp.status_code != 200:
                raise PostError(f"GitHub returned HTTP {resp.status_code} listing comments: {resp.text[:300]}")
            comments = resp.json()
            for comment in comments:
                if MARKER in (comment.get("body") or ""):
                    return comment["id"]
            if len(comments) < 100:
                return None
            page += 1
