"""
test_github_poster.py – Pytest test suite for src/github_poster.py.

All GitHub API calls are mocked so no real network traffic is generated.
Tests cover:
  - Successful comment posting
  - Finding and deleting an existing bot comment before posting
  - Graceful handling when GITHUB_TOKEN is missing
  - Graceful handling when the API returns error status codes
  - Verification that comment_url is returned on success
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock, call

import pytest
import requests

from github_poster import (
    post_pr_comment,
    _find_existing_bot_comment,
    _delete_comment,
    _build_headers,
    BOT_MARKER,
)


# ---------------------------------------------------------------------------
# Constants used across tests
# ---------------------------------------------------------------------------

SAMPLE_COMMENT = f"## 🔍 {BOT_MARKER} — `zones/example.com.txt`\n\nSample body."
REPO = "shanks5017/dns-zone-reviewer"
PR_NUMBER = 42
TOKEN = "ghp_test_token_abc123"


# ---------------------------------------------------------------------------
# Tests: _build_headers
# ---------------------------------------------------------------------------

class TestBuildHeaders:
    """Verify that API headers are constructed correctly."""

    def test_headers_contain_bearer_token(self) -> None:
        """Authorization header must use Bearer scheme."""
        headers = _build_headers(TOKEN)
        assert headers["Authorization"] == f"Bearer {TOKEN}"

    def test_headers_contain_accept(self) -> None:
        """Accept header must request GitHub v3 JSON format."""
        headers = _build_headers(TOKEN)
        assert headers["Accept"] == "application/vnd.github+json"

    def test_headers_contain_api_version(self) -> None:
        """X-GitHub-Api-Version header must be set."""
        headers = _build_headers(TOKEN)
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"


# ---------------------------------------------------------------------------
# Tests: Successful comment posting
# ---------------------------------------------------------------------------

class TestSuccessfulPost:
    """Happy path: token is present, API returns 201, comment URL returned."""

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_post_returns_success(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """post_pr_comment should return success=True on HTTP 201."""
        # No existing bot comments
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        # Successful post
        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={
                "html_url": "https://github.com/shanks5017/dns-zone-reviewer/pull/42#issuecomment-123",
            }),
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        assert result["success"] is True
        assert result["error"] == ""
        mock_post.assert_called_once()

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_comment_url_returned(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """The result dict should contain the html_url of the posted comment."""
        expected_url = "https://github.com/shanks5017/dns-zone-reviewer/pull/42#issuecomment-456"

        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"html_url": expected_url}),
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        assert result["comment_url"] == expected_url

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_post_sends_correct_payload(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """The POST request must send the comment body as JSON payload."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"html_url": "https://example.com"}),
        )

        post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        _, kwargs = mock_post.call_args
        assert kwargs["json"] == {"body": SAMPLE_COMMENT}


# ---------------------------------------------------------------------------
# Tests: Finding and deleting existing bot comment
# ---------------------------------------------------------------------------

class TestDeleteExistingBotComment:
    """When a previous bot comment exists, it should be deleted before posting."""

    @patch("github_poster.requests.delete")
    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_deletes_previous_bot_comment(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
        mock_delete: MagicMock,
    ) -> None:
        """If a comment containing BOT_MARKER exists, it must be DELETEd."""
        existing_comments = [
            {"id": 100, "body": "Some unrelated comment"},
            {"id": 200, "body": f"## 🔍 {BOT_MARKER} — `zones/old.txt`\n\nOld review."},
        ]

        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=existing_comments),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_delete.return_value = MagicMock(status_code=204)

        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"html_url": "https://example.com/new"}),
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        # Verify the DELETE was called for comment ID 200
        mock_delete.assert_called_once()
        delete_url = mock_delete.call_args[0][0]
        assert "200" in delete_url

        # Verify the new comment was still posted
        assert result["success"] is True

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_no_delete_when_no_bot_comment(
        self,
        mock_post: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        """When no bot comment exists, DELETE should not be called."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[
                {"id": 100, "body": "LGTM!"},
                {"id": 101, "body": "Please fix the TTL."},
            ]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"html_url": "https://example.com"}),
        )

        with patch("github_poster.requests.delete") as mock_delete:
            post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)
            mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: _find_existing_bot_comment
# ---------------------------------------------------------------------------

class TestFindExistingBotComment:
    """Unit tests for the helper that searches for existing bot comments."""

    @patch("github_poster.requests.get")
    def test_finds_bot_comment(self, mock_get: MagicMock) -> None:
        """Should return the comment ID when a bot comment exists."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[
                {"id": 10, "body": "unrelated"},
                {"id": 20, "body": f"blah {BOT_MARKER} blah"},
            ]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = _find_existing_bot_comment(REPO, PR_NUMBER, TOKEN)
        assert result == 20

    @patch("github_poster.requests.get")
    def test_returns_none_when_no_bot_comment(self, mock_get: MagicMock) -> None:
        """Should return None when no comment contains the bot marker."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[
                {"id": 10, "body": "Looks good to me!"},
            ]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        result = _find_existing_bot_comment(REPO, PR_NUMBER, TOKEN)
        assert result is None

    @patch("github_poster.requests.get")
    def test_returns_none_on_api_error(self, mock_get: MagicMock) -> None:
        """Should return None gracefully when the GET request fails."""
        mock_get.side_effect = requests.exceptions.ConnectionError("timeout")

        result = _find_existing_bot_comment(REPO, PR_NUMBER, TOKEN)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: Missing GITHUB_TOKEN
# ---------------------------------------------------------------------------

class TestMissingToken:
    """When the token is empty or missing, posting should fail gracefully."""

    def test_empty_token_returns_failure(self) -> None:
        """An empty token should return success=False without making API calls."""
        result = post_pr_comment(SAMPLE_COMMENT, "", REPO, PR_NUMBER)

        assert result["success"] is False
        assert "empty or missing" in result["error"].lower()
        assert result["comment_url"] == ""

    @patch("github_poster.requests.post")
    @patch("github_poster.requests.get")
    def test_empty_token_skips_api_calls(
        self, mock_get: MagicMock, mock_post: MagicMock
    ) -> None:
        """No HTTP requests should be made when token is empty."""
        post_pr_comment(SAMPLE_COMMENT, "", REPO, PR_NUMBER)

        mock_get.assert_not_called()
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: API error responses
# ---------------------------------------------------------------------------

class TestApiErrors:
    """Verify graceful handling when the GitHub API returns error status codes."""

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_403_returns_failure(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """HTTP 403 (insufficient permissions) should return success=False."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=403,
            text='{"message":"Resource not accessible by integration"}',
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        assert result["success"] is False
        assert "403" in result["error"]

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_422_returns_failure(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """HTTP 422 (validation failed) should return success=False."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=422,
            text='{"message":"Validation Failed"}',
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        assert result["success"] is False
        assert "422" in result["error"]

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_network_error_returns_failure(
        self, mock_post: MagicMock, mock_get: MagicMock
    ) -> None:
        """A network exception should return success=False with error message."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.side_effect = requests.exceptions.ConnectionError(
            "Connection refused"
        )

        result = post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        assert result["success"] is False
        assert "Request failed" in result["error"]
        assert result["comment_url"] == ""


# ---------------------------------------------------------------------------
# Tests: Fallback stdout printing
# ---------------------------------------------------------------------------

class TestFallbackPrint:
    """When posting fails, the comment body should be printed to stdout."""

    @patch("github_poster.requests.get")
    @patch("github_poster.requests.post")
    def test_fallback_prints_comment(
        self, mock_post: MagicMock, mock_get: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """On API failure, the comment body should appear in captured stdout."""
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[]),
        )
        mock_get.return_value.raise_for_status = MagicMock()

        mock_post.return_value = MagicMock(
            status_code=500,
            text='{"message":"Internal Server Error"}',
        )

        post_pr_comment(SAMPLE_COMMENT, TOKEN, REPO, PR_NUMBER)

        captured = capsys.readouterr()
        assert BOT_MARKER in captured.out

    def test_missing_token_prints_fallback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When token is empty, the comment should be printed as fallback."""
        post_pr_comment(SAMPLE_COMMENT, "", REPO, PR_NUMBER)

        captured = capsys.readouterr()
        assert BOT_MARKER in captured.out
