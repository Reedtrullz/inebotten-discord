#!/usr/bin/env python3
"""Write current git commit hash to commit_hash.txt for containerized deployments."""
import subprocess
import sys

try:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    with open("commit_hash.txt", "w") as f:
        f.write(commit)
    print(f"Wrote commit hash to commit_hash.txt: {commit}")
except subprocess.CalledProcessError as e:
    print(f"Failed to get commit hash: {e.stderr}", file=sys.stderr)
    sys.exit(1)
