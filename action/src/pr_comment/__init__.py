"""Post the verified test to the PR as a suggested file with a pass/fail badge.

Only VERIFIED tests are posted as code; UNVERIFIED results post the reason
instead, never the test body. Rendering is offline; sending is a separate,
explicit step (dry-run unless asked to post).
"""
from .github import GitHubCommenter, PostError, plan_upsert
from .render import MARKER, fence, new_file_patch, render_comment, safe_text

__all__ = [
    "MARKER",
    "GitHubCommenter",
    "PostError",
    "fence",
    "new_file_patch",
    "plan_upsert",
    "render_comment",
    "safe_text",
]
