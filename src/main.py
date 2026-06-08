"""
main.py – Entry point for the DNS Zone Reviewer GitHub Action.

Orchestrates the full review pipeline:
  1. Discover which zone files changed in the PR (differ.py)
  2. Validate each changed zone file (validator.py)
  3. Analyze changes using LLM (llm_reviewer.py)
  4. Format the final output (comment_formatter.py)
  5. Post the comment to the GitHub PR (github_poster.py)
  6. Save comment to /tmp/pr_comment.md
  7. Print a full JSON summary to stdout for CI logs
  8. Exit with code 1 if any CRITICAL findings exist, else 0
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()  # Load environment variables from .env file
except ImportError:
    pass  # python-dotenv not installed, proceed with OS env vars

# Ensure src/ is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from differ import get_changed_zones
from validator import validate_zone, ValidationResult
from llm_reviewer import analyze_with_llm
from comment_formatter import format_pr_comment
from github_poster import post_pr_comment


def _read_github_env() -> Dict[str, Any]:
    """
    Read GitHub-specific environment variables for PR posting.

    Returns
    -------
    dict[str, Any]
        A dict with keys ``github_token``, ``repo``, ``pr_number``, and
        ``available`` (bool indicating whether all required vars are set).
    """
    github_token: str = os.environ.get("GITHUB_TOKEN", "").strip()
    repo: str = os.environ.get("GITHUB_REPOSITORY", "").strip()
    pr_number_raw: str = os.environ.get("PR_NUMBER", "").strip()

    pr_number: int = 0
    if pr_number_raw:
        try:
            pr_number = int(pr_number_raw)
        except ValueError:
            print(
                f"[main] WARNING: PR_NUMBER '{pr_number_raw}' is not a valid integer.",
                file=sys.stderr,
            )

    available = bool(github_token and repo and pr_number)

    return {
        "github_token": github_token,
        "repo": repo,
        "pr_number": pr_number,
        "available": available,
    }


def main() -> None:
    """
    Run the DNS Zone Reviewer end-to-end and exit with an appropriate code.
    """
    print("DNS Zone Reviewer started", file=sys.stderr)

    # Determine base ref to diff against
    raw_base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    base_ref = f"origin/{raw_base_ref}" if raw_base_ref else "origin/main"
    print(f"[main] Comparing against base ref: {base_ref}", file=sys.stderr)

    # Read GitHub env vars (may be absent in local dev)
    gh_env = _read_github_env()
    if gh_env["available"]:
        print(
            f"[main] GitHub integration enabled — repo={gh_env['repo']}, "
            f"PR=#{gh_env['pr_number']}",
            file=sys.stderr,
        )
    else:
        print(
            "[main] GitHub env vars not fully set — skipping PR comment posting. "
            "Comment will be printed to stdout instead.",
            file=sys.stderr,
        )

    # Step 1: Discover changed zone files
    changed_zones = get_changed_zones(base_ref=base_ref)

    if not changed_zones:
        print("[main] No zone files changed – nothing to review.", file=sys.stderr)
        sys.exit(0)

    any_critical = False
    all_comments: list[str] = []
    summary_entries: list[Dict[str, Any]] = []

    for zone_diff in changed_zones:
        filename = zone_diff["filename"]
        after_content = zone_diff["after"]
        before_content = zone_diff["before"] or None
        diff_str = zone_diff["diff"]

        print(f"[main] Validating: {filename}", file=sys.stderr)

        # Step 2: Validate zone file
        if not after_content:
            # File was deleted
            result: ValidationResult = {
                "valid": True,
                "errors": [],
                "findings": [
                    {
                        "severity": "WARNING",
                        "record_type": "ZONE",
                        "description": f"Zone file '{filename}' was deleted in this PR.",
                        "record": "",
                    }
                ],
            }
        else:
            result = validate_zone(
                zone_content=after_content,
                filename=filename,
                before_content=before_content,
            )

        # Step 3: Analyze with LLM
        print(f"[main] Analyzing with LLM: {filename}", file=sys.stderr)
        llm_result = analyze_with_llm(
            diff=diff_str,
            validator_findings=result["findings"],
            filename=filename
        )
        
        # Check for critical issues
        if llm_result.get("risk_level") == "CRITICAL" or not result.get("valid"):
            any_critical = True
            
        # Step 4: Format comment
        comment = format_pr_comment(filename, result, llm_result)
        all_comments.append(comment)

        # Build summary entry for JSON output
        summary_entries.append({
            "filename": filename,
            "valid": result.get("valid", False),
            "risk_level": llm_result.get("risk_level", "UNKNOWN"),
            "findings_count": len(result.get("findings", [])),
            "llm_findings_count": len(llm_result.get("llm_findings", [])),
            "safe_to_merge": llm_result.get("safe_to_merge", True),
            "llm_available": llm_result.get("llm_available", False),
            "model_used": llm_result.get("model_used", "none"),
        })

    # Combine all per-file comments into one PR comment
    full_comment = "\n\n".join(all_comments)

    # Step 5: Post to GitHub PR (if env vars are available)
    post_result: Dict[str, Any] = {
        "success": False,
        "comment_url": "",
        "error": "GitHub env vars not available (local development)",
    }

    if gh_env["available"]:
        print("[main] Posting comment to GitHub PR...", file=sys.stderr)
        post_result = post_pr_comment(
            comment_body=full_comment,
            github_token=gh_env["github_token"],
            repo=gh_env["repo"],
            pr_number=gh_env["pr_number"],
        )
    else:
        # Local development fallback: print comment to stdout safely for Windows
        try:
            print("\n" + full_comment + "\n")
        except UnicodeEncodeError:
            # Fallback for terminals that don't support emojis (like standard Windows cmd/powershell)
            safe_comment = full_comment.encode('ascii', 'replace').decode('ascii')
            print("\n" + safe_comment + "\n")
            print("[main] Note: Some emojis could not be printed to the terminal, but the markdown file is intact.", file=sys.stderr)

    # Step 6: Save to /tmp/pr_comment.md
    output_path = Path("/tmp/pr_comment.md")
    
    try:
        # Create parent directories if they don't exist (helpful for local testing on Windows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_comment)
        print(f"[main] Saved PR comment to {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"[main] Failed to write PR comment to {output_path}: {e}", file=sys.stderr)

    # Step 7: Print full JSON summary to stdout for CI logs
    ci_summary: Dict[str, Any] = {
        "dns_zone_reviewer": {
            "version": "0.1.0",
            "files_reviewed": len(changed_zones),
            "any_critical": any_critical,
            "github_comment": {
                "posted": post_result.get("success", False),
                "url": post_result.get("comment_url", ""),
                "error": post_result.get("error", ""),
            },
            "file_results": summary_entries,
        }
    }
    print(json.dumps(ci_summary, indent=2))

    # Step 8: Exit with appropriate code
    if any_critical:
        print("\n[main] ❌ CRITICAL findings detected – exiting with code 1.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n[main] ✅ No critical findings – exiting with code 0.", file=sys.stderr)
        sys.exit(0)

if __name__ == "__main__":
    main()
