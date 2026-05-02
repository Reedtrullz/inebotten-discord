#!/usr/bin/env python3
"""Write current git commit hash to commit_hash.txt for containerized deployments."""
import subprocess
import os
import subprocess
import urllib.request
import json

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
        try:
            # Fallback 2: Fetch latest from GitHub API since Coolify strips .git
            req = urllib.request.Request(
                "https://api.github.com/repos/Reedtrullz/inebotten-discord/commits/master",
                headers={"User-Agent": "Inebotten-Build"}
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                commit = data["sha"][:7]
                print("Fetched commit hash from GitHub API!")
        except Exception as e:
            print(f"GitHub API fallback failed: {e}")
            commit = "unknown"

with open("commit_hash.txt", "w") as f:
    f.write(commit)
print(f"Wrote commit hash to commit_hash.txt: {commit}")
