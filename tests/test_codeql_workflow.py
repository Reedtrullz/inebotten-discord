"""Keep every required analysis running, including dependency-only PRs."""

from pathlib import Path
import re

import yaml


def test_codeql_runs_all_required_languages_without_path_or_actor_filters():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load(
        (root / ".github/workflows/codeql.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    events = workflow["on"]
    assert set(events) == {"push", "pull_request", "schedule"}
    for event in ("push", "pull_request"):
        assert events[event] == {"branches": ["master", "main"]}
    assert events["schedule"]
    assert "pull_request_target" not in events

    job = workflow["jobs"]["analyze"]
    assert job["name"] == "Analyze (${{ matrix.language }})"
    assert set(job["strategy"]["matrix"]["language"]) == {
        "actions", "javascript-typescript", "python",
    }
    assert job["strategy"]["fail-fast"] == "false"
    assert "if" not in job and "continue-on-error" not in job
    assert job["permissions"]["security-events"] == "write"
    assert job["permissions"]["contents"] == "read"
    steps = job["steps"]
    assert all("if" not in step and "continue-on-error" not in step for step in steps)
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", step["uses"]) for step in steps)
    assert steps[1]["uses"].startswith("github/codeql-action/init@")
    assert steps[1]["with"] == {
        "languages": "${{ matrix.language }}", "build-mode": "none",
    }
    assert steps[2]["uses"].startswith("github/codeql-action/analyze@")
    assert steps[2]["with"] == {"category": "/language:${{ matrix.language }}"}
