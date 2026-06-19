#!/usr/bin/env python3
"""Repository guardrails for paths that must not be tracked."""

from __future__ import annotations

import subprocess
import sys


ALLOWED_STAGING_PATHS = {"staging/README.md"}


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    errors: list[str] = []

    tracked_staging = [
        path
        for path in git_lines("ls-files", "staging")
        if path not in ALLOWED_STAGING_PATHS
    ]
    if tracked_staging:
        errors.append(
            "Tracked staging material is forbidden; only staging/README.md may be tracked."
        )
        errors.extend(f"  tracked: {path}" for path in tracked_staging)

    staged_staging = [
        path
        for path in git_lines(
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--",
            "staging",
        )
        if path not in ALLOWED_STAGING_PATHS
    ]
    if staged_staging:
        errors.append(
            "Staged additions/modifications under staging/ are forbidden; keep drafts ignored."
        )
        errors.extend(f"  staged: {path}" for path in staged_staging)

    tracked_data = git_lines("ls-files", ".data")
    if tracked_data:
        errors.append("Tracked .data payload material is forbidden.")
        errors.extend(f"  tracked: {path}" for path in tracked_data)

    staged_data = git_lines(
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "--",
        ".data",
    )
    if staged_data:
        errors.append("Staged additions/modifications under .data/ are forbidden.")
        errors.extend(f"  staged: {path}" for path in staged_data)

    if errors:
        print("repository hygiene check failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("repository hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
