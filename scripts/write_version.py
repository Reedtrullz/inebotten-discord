#!/usr/bin/env python3
"""Write current git commit hash to commit_hash.txt for containerized deployments."""
import subprocess
import sys

import os

commit = os.environ.get("SOURCE_COMMIT")

if not commit:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        commit = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Failed to get commit hash via git: {e}", file=sys.stderr)
        sys.exit(1)

with open("commit_hash.txt", "w") as f:
    f.write(commit)
print(f"Wrote commit hash to commit_hash.txt: {commit}")
