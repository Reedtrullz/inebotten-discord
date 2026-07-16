"""CI order contract for the deterministic NLU acceptance gate."""

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml"


def test_ci_runs_offline_proof_in_the_required_order():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    steps = (
        "Compile Python files",
        "Check for syntax errors and undefined names",
        "Run non-browser tests",
        "Evaluate production NLU contract",
        "Upload NLU contract report",
        "Install Playwright Chromium",
        "Run browser tests",
    )

    positions = [workflow.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "if: always()" in workflow
    assert "uses: actions/upload-artifact@v4" in workflow
    assert "--corpus tests/fixtures/nlu_contract_v1.jsonl" in workflow
    assert "--report .artifacts/nlu-contract.json" in workflow
    assert "\\.venv312" in workflow
    assert "--exclude=.git,.venv,.venv312,__pycache__,.pytest_cache" in workflow
