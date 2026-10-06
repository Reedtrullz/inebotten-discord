#!/usr/bin/env python3
"""Run pytest with private, run-local paths and explicit live-test opt-ins."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--live-provider", action="store_true")
    parser.add_argument("--live-account", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pytest_args = args.pytest_args
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    scratch = ROOT / ".superpowers" / "test-runs"
    scratch.mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in (
        "PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "SSL_CERT_FILE",
        "SSL_CERT_DIR", "PLAYWRIGHT_BROWSERS_PATH",
    ) if key in os.environ}
    if "PLAYWRIGHT_BROWSERS_PATH" not in env:
        cache = Path.home() / (
            "Library/Caches/ms-playwright" if sys.platform == "darwin"
            else ".cache/ms-playwright"
        )
        if cache.is_dir():
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache)
    for enabled, names in (
        (args.live_provider, (
            "OPENROUTER_API_KEY", "OPENROUTER_BASE_URL", "OPENROUTER_MODEL",
            "HERMES_API_URL", "HERMES_BRIDGE_API_KEY", "LM_STUDIO_URL",
        )),
        (args.live_account, ("DISCORD_USER_TOKEN",)),
    ):
        if enabled:
            env.update({key: os.environ[key] for key in names if key in os.environ})
    with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
        runtime = Path(temporary)
        env.update(
            HOME=str(runtime / "home"),
            USERPROFILE=str(runtime / "home"),
            HERMES_HOME=str(runtime / "hermes"),
            XDG_CONFIG_HOME=str(runtime / "config"),
            XDG_CACHE_HOME=str(runtime / "cache"),
            TMPDIR=str(runtime), TEMP=str(runtime), TMP=str(runtime),
            PYTHONPATH=os.pathsep.join((str(ROOT / "tests/support"), str(ROOT))),
            INEBOTTEN_OFFLINE_TESTS="1",
            INEBOTTEN_LIVE_PROVIDER=str(int(args.live_provider)),
            INEBOTTEN_LIVE_ACCOUNT=str(int(args.live_account)),
        )
        Path(env["HOME"]).mkdir()
        command = [
            args.python, "-m", "pytest", "-p", "inebotten_offline",
            "--rootdir", str(ROOT), *pytest_args,
        ]
        try:
            return subprocess.run(command, cwd=ROOT, env=env).returncode
        except KeyboardInterrupt:
            return 130


if __name__ == "__main__":
    raise SystemExit(main())
