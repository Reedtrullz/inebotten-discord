"""Exercise the offline launcher in child processes without importing the app."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_offline_tests.py"
SCRATCH = ROOT / ".superpowers" / "test-environment"
SCRATCH.mkdir(parents=True, exist_ok=True)


class OfflineEnvironmentTests(unittest.TestCase):
    def run_probe(self, source, *, inherited=None, args=()):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            root = Path(directory)
            outside = root / "outside"
            outside.mkdir()
            sentinel = outside / "keep.txt"
            sentinel.write_bytes(b"untouched")
            probe = root / "test_probe.py"
            probe.write_text(source.replace("OUTSIDE_LITERAL", repr(str(outside))))
            env = os.environ.copy()
            env.update(HERMES_HOME=str(outside), OPENROUTER_API_KEY="fake-private-key")
            env.update(inherited or {})
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--python", sys.executable,
                 "--", str(probe), "-q", *args],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(sentinel.read_bytes(), b"untouched")
            self.assertEqual(list(outside.iterdir()), [sentinel])
            return result

    def test_inherited_hermes_is_untouched(self):
        result = self.run_probe("""
def test_import_boundary():
    import os
    from pathlib import Path
    from core.config import Config
    from utils.json_storage import hermes_home_path
    assert Path(os.environ["HERMES_HOME"]) != Path(OUTSIDE_LITERAL)
    assert hermes_home_path() != Path(OUTSIDE_LITERAL)
    assert os.environ.get("OPENROUTER_API_KEY") != "fake-private-key"
    assert not Config().OPENROUTER_API_KEY
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_external_network_is_blocked(self):
        result = self.run_probe("""
def test_network_boundary():
    import socket
    import pytest
    with pytest.raises(OSError, match="offline"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(OSError, match="offline"):
        socket.socket().connect(("192.0.2.1", 443))
    assert socket.getaddrinfo("127.0.0.1", 443)
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_parallel_console_ports_differ(self):
        result = self.run_probe("""
import asyncio
def test_ephemeral_servers():
    from web_console.server import ConsoleServer
    async def scenario():
        first = ConsoleServer(host="127.0.0.1", port=0, api_key="fixture-key")
        second = ConsoleServer(host="127.0.0.1", port=0, api_key="fixture-key")
        try:
            await first.start()
            await second.start()
            assert first.actual_port > 0 and second.actual_port > 0
            assert first.actual_port != second.actual_port
        finally:
            await first.stop()
            await second.stop()
    asyncio.run(scenario())
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_live_markers_are_skipped_without_explicit_flag(self):
        result = self.run_probe("""
import pytest
@pytest.mark.live_provider
def test_real_provider():
    raise AssertionError("live provider must not run by default")
def test_offline():
    assert True
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 skipped", result.stdout)


if __name__ == "__main__":
    unittest.main()
