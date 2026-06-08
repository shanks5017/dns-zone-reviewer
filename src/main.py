"""
main.py – Entry point for the DNS Zone Reviewer GitHub Action.

Orchestrates the full review pipeline:
  1. Discover which zone files changed in the PR (differ.py)
  2. Validate each changed zone file (validator.py)
  3. Analyze changes using LLM (llm_reviewer.py)
  4. Format the final output (comment_formatter.py)
  5. Print a structured report to stdout and save to /tmp/pr_comment.md
  6. Exit with code 1 if any CRITICAL findings exist, else 0
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure src/ is importable when run directly
sys.path.insert(0, os.path.dirname(__file__))

from differ import get_changed_zones
from validator import validate_zone, ValidationResult
from llm_reviewer import analyze_with_llm
from comment_formatter import format_pr_comment

def main() -> None:
    """
    Run the DNS Zone Reviewer end-to-end and exit with an appropriate code.
    """
    print("DNS Zone Reviewer started", file=sys.stderr)

    # Determine base ref to diff against
    raw_base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    base_ref = f"origin/{raw_base_ref}" if raw_base_ref else "origin/main"
    print(f"[main] Comparing against base ref: {base_ref}", file=sys.stderr)

    # Step 1: Discover changed zone files
    changed_zones = get_changed_zones(base_ref=base_ref)

    if not changed_zones:
        print("[main] No zone files changed – nothing to review.", file=sys.stderr)
        sys.exit(0)

    any_critical = False
    all_comments = []

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
        
        # Print to stdout
        print("\n" + comment + "\n")

    # Step 5: Save to /tmp/pr_comment.md
    full_comment = "\n\n".join(all_comments)
    output_path = Path("/tmp/pr_comment.md")
    
    try:
        # Create parent directories if they don't exist (helpful for local testing on Windows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_comment)
        print(f"[main] Saved PR comment to {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"[main] Failed to write PR comment to {output_path}: {e}", file=sys.stderr)

    # Step 6: Exit with appropriate code
    if any_critical:
        print("\n[main] ❌ CRITICAL findings detected – exiting with code 1.", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n[main] ✅ No critical findings – exiting with code 0.", file=sys.stderr)
        sys.exit(0)

if __name__ == "__main__":
    main()
