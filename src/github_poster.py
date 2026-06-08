"""
github_poster.py – Post DNS Zone Review comments to GitHub PRs.

Handles the full lifecycle of a bot comment on a pull request:
  1. List existing comments and delete any previous bot comment
  2. Post a fresh comment with the latest review results
  3. Return a structured result dict for CI logging

When the GitHub API is unreachable or credentials are missing, the module
gracefully degrades by printing the comment body to stdout so it remains
visible in CI logs.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

import requests

# Marker string used to identify comments posted by this bot.
# We search for this substring when deciding whether to delete a stale comment.
BOT_MARKER: str = "DNS Zone Review Bot"


def _find_existing_bot_comment(
    repo: str,
    pr_number: int,
    github_token: str,
) -> Optional[int]:
    """
    Search for a previous bot comment on the PR and return its comment ID.

    Iterates through all issue comments on the PR and looks for the
    :data:`BOT_MARKER` substring in the comment body.

    Parameters
    ----------
    repo:
        GitHub repository in ``"owner/name"`` format.
    pr_number:
        Pull request number.
    github_token:
        Personal access token or ``GITHUB_TOKEN`` with ``pull-requests: write``
        permission.

    Returns
    -------
    int | None
        The comment ID of the first matching bot comment, or ``None`` if no
        previous bot comment exists.
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = _build_headers(github_token)

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        for comment in response.json():
            body: str = comment.get("body", "")
            if BOT_MARKER in body:
                return int(comment["id"])

    except requests.exceptions.RequestException as exc:
        print(
            f"[github_poster] WARNING: Failed to list PR comments: {exc}",
            file=sys.stderr,
        )

    return None


def _delete_comment(
    repo: str,
    comment_id: int,
    github_token: str,
) -> bool:
    """
    Delete a single issue comment by ID.

    Parameters
    ----------
    repo:
        GitHub repository in ``"owner/name"`` format.
    comment_id:
        The numeric ID of the comment to delete.
    github_token:
        GitHub API token.

    Returns
    -------
    bool
        ``True`` if the comment was successfully deleted, ``False`` otherwise.
    """
    url = f"https://api.github.com/repos/{repo}/issues/comments/{comment_id}"
    headers = _build_headers(github_token)

    try:
        response = requests.delete(url, headers=headers, timeout=30)
        if response.status_code in (200, 204):
            print(
                f"[github_poster] Deleted previous bot comment (ID: {comment_id})",
                file=sys.stderr,
            )
            return True
        else:
            print(
                f"[github_poster] WARNING: Failed to delete comment {comment_id}: "
                f"HTTP {response.status_code}",
                file=sys.stderr,
            )
            return False

    except requests.exceptions.RequestException as exc:
        print(
            f"[github_poster] WARNING: Failed to delete comment {comment_id}: {exc}",
            file=sys.stderr,
        )
        return False


def _build_headers(github_token: str) -> Dict[str, str]:
    """
    Build the standard GitHub REST API v3 request headers.

    Parameters
    ----------
    github_token:
        Bearer token for authentication.

    Returns
    -------
    dict[str, str]
        Headers dict ready to pass to ``requests.*`` calls.
    """
    return {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def post_pr_comment(
    comment_body: str,
    github_token: str,
    repo: str,
    pr_number: int,
) -> Dict[str, Any]:
    """
    Post a review comment on a GitHub pull request.

    If a previous bot comment (identified by :data:`BOT_MARKER` in its body)
    already exists on the PR, it is deleted first to avoid spamming multiple
    comments on successive pushes.

    Parameters
    ----------
    comment_body:
        The full markdown comment to post on the PR.
    github_token:
        GitHub API token (typically ``$GITHUB_TOKEN`` from Actions).
    repo:
        Repository in ``"owner/name"`` format, e.g.
        ``"shanks5017/dns-zone-reviewer"``.
    pr_number:
        The pull request number.

    Returns
    -------
    dict[str, Any]
        A result dict with the following keys:

        - ``success`` (bool): Whether the comment was posted successfully.
        - ``comment_url`` (str): URL of the posted comment, or empty string
          on failure.
        - ``error`` (str): Error message if posting failed, or empty string
          on success.
    """
    # Guard: missing token
    if not github_token:
        _fallback_print(comment_body, reason="GITHUB_TOKEN is empty or missing")
        return {
            "success": False,
            "comment_url": "",
            "error": "GITHUB_TOKEN is empty or missing",
        }

    # Step 1: Delete any previous bot comment
    existing_id = _find_existing_bot_comment(repo, pr_number, github_token)
    if existing_id is not None:
        _delete_comment(repo, existing_id, github_token)

    # Step 2: Post the new comment
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = _build_headers(github_token)
    payload = {"body": comment_body}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code in (200, 201):
            comment_data = response.json()
            comment_url: str = comment_data.get("html_url", "")
            print(
                f"[github_poster] ✅ Comment posted: {comment_url}",
                file=sys.stderr,
            )
            return {
                "success": True,
                "comment_url": comment_url,
                "error": "",
            }
        else:
            error_msg = (
                f"GitHub API returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )
            print(
                f"[github_poster] ❌ {error_msg}",
                file=sys.stderr,
            )
            _fallback_print(comment_body, reason=error_msg)
            return {
                "success": False,
                "comment_url": "",
                "error": error_msg,
            }

    except requests.exceptions.RequestException as exc:
        error_msg = f"Request failed: {exc}"
        print(
            f"[github_poster] ❌ {error_msg}",
            file=sys.stderr,
        )
        _fallback_print(comment_body, reason=error_msg)
        return {
            "success": False,
            "comment_url": "",
            "error": error_msg,
        }


def _fallback_print(comment_body: str, reason: str) -> None:
    """
    Print the comment body to stdout as a fallback when posting fails.

    This ensures the review content is always visible in CI logs even
    when the GitHub API is unavailable.

    Parameters
    ----------
    comment_body:
        The markdown comment that could not be posted.
    reason:
        Human-readable explanation of why posting failed.
    """
    print(
        f"\n{'=' * 60}\n"
        f"[github_poster] FALLBACK: Could not post to GitHub ({reason})\n"
        f"[github_poster] Printing comment to stdout instead:\n"
        f"{'=' * 60}\n",
        file=sys.stderr,
    )
    print(comment_body)
