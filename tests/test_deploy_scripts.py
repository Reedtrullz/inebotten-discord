from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "write_version.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "commit = os.environ.get('SOURCE_COMMIT', 'unknown')\n"
        "Path('commit_hash.txt').write_text(commit, encoding='utf-8')\n"
        "print(f'wrote {commit}')\n",
        encoding="utf-8",
    )
    return repo


def _make_fake_bin(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "flock",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_executable(
        fake_bin / "date",
        """#!/usr/bin/env bash
echo "2026-06-12T12:00:00+00:00"
""",
    )
    _write_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  fetch)
    exit 0
    ;;
  reset)
    echo "$*" >> "$FAKE_LOG_DIR/git.log"
    exit 0
    ;;
  rev-parse)
    if [ "$2" = "--short" ]; then
      echo "$FAKE_SHORT"
    elif [ "$2" = "HEAD" ]; then
      echo "$FAKE_HEAD"
    else
      echo "$FAKE_ORIGIN"
    fi
    exit 0
    ;;
esac
echo "unexpected git $*" >> "$FAKE_LOG_DIR/git.log"
exit 1
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "compose" ] && [ "${2:-}" = "version" ]; then
  exit 0
fi
if [ "$1" = "compose" ] && [ "${2:-}" = "up" ]; then
  echo "$*" >> "$FAKE_LOG_DIR/docker.log"
  exit 0
fi
if [ "$1" = "exec" ]; then
  printf '%s' "${FAKE_RUNNING_COMMIT:-}"
  exit 0
fi
if [ "$1" = "image" ] && [ "${2:-}" = "prune" ]; then
  exit 0
fi
echo "unexpected docker $*" >> "$FAKE_LOG_DIR/docker.log"
exit 1
""",
    )
    return fake_bin


def _run_update(tmp_path: Path, *, running_commit: str) -> Path:
    repo = _make_fake_repo(tmp_path)
    fake_bin = _make_fake_bin(tmp_path)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "INEBOTTEN_REPO": str(repo),
        "INEBOTTEN_UPDATE_LOG": str(log_dir / "update.log"),
        "INEBOTTEN_UPDATE_LOCK": str(log_dir / "update.lock"),
        "FAKE_LOG_DIR": str(log_dir),
        "FAKE_HEAD": "517cabb25a145c95dab06b0b1ca22f7e5ecae7a2",
        "FAKE_ORIGIN": "517cabb25a145c95dab06b0b1ca22f7e5ecae7a2",
        "FAKE_SHORT": "517cabb",
        "FAKE_RUNNING_COMMIT": running_commit,
    }
    subprocess.run(
        ["bash", str(PROJECT_ROOT / "scripts/deploy/inebotten-update")],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return log_dir


def test_update_rebuilds_when_checkout_is_current_but_container_is_old(tmp_path):
    log_dir = _run_update(tmp_path, running_commit="1e3e532")

    docker_log = (log_dir / "docker.log").read_text(encoding="utf-8")
    update_log = (log_dir / "update.log").read_text(encoding="utf-8")

    assert "compose up -d --build --remove-orphans" in docker_log
    assert "Running container is at 1e3e532; expected 517cabb" in update_log


def test_update_skips_rebuild_when_container_already_matches_head(tmp_path):
    log_dir = _run_update(tmp_path, running_commit="517cabb")

    assert not (log_dir / "docker.log").exists()
    update_log = (log_dir / "update.log").read_text(encoding="utf-8")
    assert "Already deployed at 517cabb" in update_log


def test_install_autoupdate_preserves_existing_secret_and_restarts_services():
    content = (PROJECT_ROOT / "scripts/deploy/install-autoupdate.sh").read_text(encoding="utf-8")

    assert 'existing_env_value WEBHOOK_SECRET' in content
    assert 'systemctl restart inebotten-webhook.service' in content
    assert 'systemctl restart inebotten-update.timer' in content
