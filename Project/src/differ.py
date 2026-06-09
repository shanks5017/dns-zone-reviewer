"""
differ.py – Git-based zone-file differ for the DNS Zone Reviewer.

Discovers which zones/*.txt files changed in the current PR, then
produces a unified diff alongside the BEFORE and AFTER content of
each changed file.  All git interaction is done via subprocess so
there is no third-party dependency beyond the standard library.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


# ---------------------------------------------------------------------------
# Public type contract
# ---------------------------------------------------------------------------

class ZoneDiff(TypedDict):
    """Structured result returned for every changed zone file."""

    filename: str          # relative path, e.g. "zones/example.com.txt"
    before: str            # full content from git HEAD (empty string for new files)
    after: str             # full content on disk right now (empty string for deleted files)
    diff: str              # unified diff string ready for display / AI prompting


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """
    Run a git command and return the CompletedProcess result.

    Parameters
    ----------
    *args:
        Tokens passed directly to git, e.g. ("diff", "--name-only", "HEAD").
    cwd:
        Working directory for the command.  Defaults to the current directory.

    Returns
    -------
    subprocess.CompletedProcess
        stdout / stderr are captured as text; the call never raises on a
        non-zero exit code so callers can inspect returncode themselves.
    """
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _get_changed_filenames(base_ref: str, cwd: Path) -> list[str]:
    """
    Return a list of zone file paths that differ between *base_ref* and HEAD.

    Uses ``git diff --name-only`` which lists every file touched (added,
    modified, deleted, renamed) regardless of the type of change.

    Parameters
    ----------
    base_ref:
        The git ref representing the PR base branch, e.g. ``"origin/main"``.
    cwd:
        Repository root directory.

    Returns
    -------
    list[str]
        Relative file paths filtered to ``zones/*.txt`` only.
    """
    result = _run_git("diff", "--name-only", base_ref, "HEAD", cwd=cwd)

    if result.returncode != 0:
        # Fallback: compare against the immediate parent commit.
        # This handles shallow clones where origin/main may not be available.
        result = _run_git("diff", "--name-only", "HEAD^", "HEAD", cwd=cwd)

    if result.returncode != 0:
        print(
            f"[differ] WARNING: git diff failed: {result.stderr.strip()}",
            file=sys.stderr,
        )
        return []

    all_changed = result.stdout.strip().splitlines()

    # Keep only zone files – ignore unrelated paths that may appear in a PR
    zone_files = [
        f for f in all_changed
        if f.startswith("zones/") and f.endswith(".txt")
    ]
    return zone_files


def _get_file_content_at_ref(filepath: str, ref: str, cwd: Path) -> str:
    """
    Retrieve the content of *filepath* at a specific git *ref*.

    Parameters
    ----------
    filepath:
        Repository-relative path, e.g. ``"zones/example.com.txt"``.
    ref:
        Any git ref: commit SHA, branch name, ``"HEAD"``, ``"HEAD^"``, etc.
    cwd:
        Repository root directory.

    Returns
    -------
    str
        File content, or an empty string when the file does not exist at
        that ref (i.e. the file was newly added in this PR).
    """
    result = _run_git("show", f"{ref}:{filepath}", cwd=cwd)

    if result.returncode != 0:
        # File did not exist at this ref (new file added in the PR)
        return ""

    return result.stdout


def _get_current_file_content(filepath: str, cwd: Path) -> str:
    """
    Read the *current on-disk* content of a file (the AFTER state).

    Parameters
    ----------
    filepath:
        Repository-relative path.
    cwd:
        Repository root directory.

    Returns
    -------
    str
        File content, or an empty string when the file no longer exists
        on disk (i.e. it was deleted in this PR).
    """
    abs_path = cwd / filepath
    try:
        return abs_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # File was deleted in this PR
        return ""


def _build_unified_diff(before: str, after: str, filename: str) -> str:
    """
    Produce a human-readable unified diff between *before* and *after*.

    Parameters
    ----------
    before:
        Old file content (may be empty for new files).
    after:
        New file content (may be empty for deleted files).
    filename:
        Used as the label in the diff header.

    Returns
    -------
    str
        Unified diff string, including the ``---``/``+++`` header lines.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)

    diff_lines = difflib.unified_diff(
        before_lines,
        after_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    )
    return "\n".join(diff_lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_changed_zones(
    repo_root: str | Path | None = None,
    base_ref: str = "origin/main",
) -> list[ZoneDiff]:
    """
    Discover and diff all ``zones/*.txt`` files changed in the current PR.

    This function is the primary entry-point for the differ module.  It is
    intentionally side-effect free (read-only git operations + file reads)
    so it is safe to call from tests or from multiple places.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.  When *None*, the current
        working directory is used (which is correct when the workflow runs
        inside the checked-out repo).
    base_ref:
        The git ref for the PR base branch.  Defaults to ``"origin/main"``;
        can be overridden via ``GITHUB_BASE_REF`` in CI environments.

    Returns
    -------
    list[ZoneDiff]
        One entry per changed zone file.  The list is empty when no zone
        files changed (the workflow path filter should prevent this, but
        defensive coding never hurts).

    Example
    -------
    >>> diffs = get_changed_zones()
    >>> for d in diffs:
    ...     print(d["filename"], "changed")
    """
    cwd = Path(repo_root) if repo_root else Path.cwd()

    changed_files = _get_changed_filenames(base_ref=base_ref, cwd=cwd)

    if not changed_files:
        print("[differ] No zone files changed in this PR.", file=sys.stderr)
        return []

    results: list[ZoneDiff] = []

    for filepath in changed_files:
        print(f"[differ] Processing: {filepath}", file=sys.stderr)

        # Fetch content at the PR base (BEFORE) and on disk (AFTER)
        before_content = _get_file_content_at_ref(
            filepath=filepath,
            ref=base_ref,
            cwd=cwd,
        )
        after_content = _get_current_file_content(filepath=filepath, cwd=cwd)

        unified_diff = _build_unified_diff(
            before=before_content,
            after=after_content,
            filename=filepath,
        )

        results.append(
            ZoneDiff(
                filename=filepath,
                before=before_content,
                after=after_content,
                diff=unified_diff,
            )
        )

    return results
