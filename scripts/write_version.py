#!/usr/bin/env python3
"""Write the current git commit hash to commit_hash.txt for deployments."""

from __future__ import annotations

import argparse
import os
import re
import sys
import subprocess
from pathlib import Path


COMMIT_FILE = Path("commit_hash.txt")


def _clean_commit(value: str | None) -> str | None:
    commit = (value or "").strip()
    return commit or None


def _commit_from_env() -> tuple[str, str] | None:
    for key in ("SOURCE_COMMIT", "COMMIT_SHA"):
        commit = _clean_commit(os.environ.get(key))
        if commit:
            return commit, key
    return None


def _commit_from_git() -> tuple[str, str] | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None

    commit = _clean_commit(result.stdout)
    if not commit:
        return None
    return commit, "git"


def _commit_from_existing_file(path: Path) -> tuple[str, str] | None:
    try:
        if not path.exists():
            return None
        commit = _clean_commit(path.read_text(encoding="utf-8"))
    except OSError:
        return None

    if not commit:
        return None
    return commit, str(path)


def resolve_commit(path: Path = COMMIT_FILE) -> tuple[str, str]:
    """Return (commit, source), preferring env, git, then existing file."""
    for getter in (_commit_from_env, _commit_from_git):
        resolved = getter()
        if resolved is not None:
            return resolved

    existing = _commit_from_existing_file(path)
    if existing is not None:
        return existing

    return "unknown", "unknown"


def write_commit(commit: str, path: Path = COMMIT_FILE) -> None:
    path.write_text(commit, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-full", action="store_true")
    args = parser.parse_args(argv or [])
    commit, source = resolve_commit(COMMIT_FILE)
    if args.require_full and not re.fullmatch("[0-9a-f]{40}", commit):
        print("A full source revision is required; commit metadata was not overwritten")
        return 1
    if source == "unknown":
        print("No SOURCE_COMMIT/COMMIT_SHA, no local git metadata, and no existing commit_hash.txt; using unknown")
    write_commit(commit, COMMIT_FILE)
    print(f"Wrote commit hash to commit_hash.txt: {commit} ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
