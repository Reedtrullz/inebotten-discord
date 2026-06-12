#!/usr/bin/env python3
"""Write current git commit hash to commit_hash.txt for containerized deployments."""
import subprocess
import os

commit = os.environ.get("SOURCE_COMMIT") or os.environ.get("COMMIT_SHA")

if not commit:
    try:
        # Fallback 1: Try git (if .git is present)
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("No SOURCE_COMMIT/COMMIT_SHA and no local git metadata; using unknown")
        commit = "unknown"

with open("commit_hash.txt", "w") as f:
    f.write(commit)
print(f"Wrote commit hash to commit_hash.txt: {commit}")
