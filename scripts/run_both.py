#!/usr/bin/env python3
"""
Discord Selfbot + Hermes Bridge Combined Runner
Starts both services together with proper coordination

This script handles dynamic path resolution and coordinates the startup
of the bridge server and the selfbot client.
"""

import os
import sys
import asyncio
import signal
import time
import subprocess
import threading
import requests
from pathlib import Path
from datetime import datetime
from utils.logger import setup_logger

# Setup logging
logger = setup_logger(__name__, log_level="INFO")

# Path configuration
SCRIPT_DIR = Path(__file__).parent.absolute()
BASE_DIR = SCRIPT_DIR.parent.absolute()

# Services
BRIDGE_SERVER_PATH = BASE_DIR / "ai" / "hermes_bridge_server.py"
SELFBOT_RUNNER_PATH = BASE_DIR / "core" / "selfbot_runner.py"

# Configuration
BRIDGE_HOST = os.getenv("HERMES_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("HERMES_BRIDGE_PORT", "3000"))
BRIDGE_URL = f"http://{BRIDGE_HOST}:{BRIDGE_PORT}"
BRIDGE_HEALTH_URL = f"{BRIDGE_URL}/health"
BRIDGE_READY_TIMEOUT = 30  # seconds to wait for bridge


class CombinedRunner:
    """Runs both Hermes Bridge and Discord Selfbot together"""

    def __init__(self):
        self.bridge_process = None
        self.selfbot_runner = None
        self.running = False
        self.shutdown_event = asyncio.Event()

    def log(self, message):
        """Print with timestamp"""
        logger.info(message)

    async def start_bridge(self):
        """Start the Hermes Bridge Server as a subprocess"""
        self.log("")
        self.log("=" * 60)
        self.log("STARTING HERMES BRIDGE SERVER")
        self.log("=" * 60)

        # Check if bridge is already running
        try:
            response = requests.get(BRIDGE_HEALTH_URL, timeout=5)
            if response.status_code == 200:
                data = response.json()
                lm_status = data.get("lm_studio", "unknown")
                self.log(f"✓ Bridge already running! LM Studio: {lm_status}")
                self.log("  (Using existing bridge instance)")
                return True
        except requests.exceptions.Timeout:
            logger.warning("Bridge health check timed out")
        except Exception as e:
            logger.debug(f"Bridge check error: {e}")

        # Get the path to the bridge server
        bridge_script = BRIDGE_SERVER_PATH
        if not bridge_script.exists():
            # Fallback for different directory structures
            bridge_script = BASE_DIR / "hermes_bridge_server.py"
            if not bridge_script.exists():
                self.log(f"ERROR: Bridge script not found at {BRIDGE_SERVER_PATH}")
                return False

        # Start bridge in subprocess with unbuffered output
        self.log(f"Starting bridge from {bridge_script}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        # Ensure the project root is in PYTHONPATH
        env["PYTHONPATH"] = str(BASE_DIR) + os.pathsep + env.get("PYTHONPATH", "")

        self.bridge_process = subprocess.Popen(
            [sys.executable, "-u", str(bridge_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env,
            cwd=str(BASE_DIR)
        )

        self.log(f"Bridge process started (PID: {self.bridge_process.pid})")

        # Wait for bridge to be ready
        self.log(f"Waiting for bridge to be ready...")

        start_time = time.time()
        while time.time() - start_time < BRIDGE_READY_TIMEOUT:
            try:
                response = requests.get(BRIDGE_HEALTH_URL, timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    lm_status = data.get("lm_studio", "unknown")
                    self.log(f"✓ Bridge ready! LM Studio: {lm_status}")
                    return True
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                pass
            except Exception as e:
                logger.debug(f"Waiting for bridge: {e}")

            # Check if bridge process died
            if self.bridge_process.poll() is not None:
                self.log(f"ERROR: Bridge process exited with code {self.bridge_process.poll()}")
                return False

            await asyncio.sleep(1)

        self.log(f"ERROR: Bridge failed to start within {BRIDGE_READY_TIMEOUT}s")
        return False

    def _stream_bridge_output_sync(self):
        """Stream bridge output in a separate thread"""
        if not self.bridge_process or not self.bridge_process.stdout:
            return

        try:
            for line in iter(self.bridge_process.stdout.readline, ''):
                if not self.running:
                    break
                if line:
                    print(f"[BRIDGE] {line.rstrip()}", flush=True)
        except Exception as e:
            logger.error(f"Bridge output error: {e}")

    async def start_selfbot(self):
        """Start the Discord Selfbot in the current process/loop"""
        self.log("")
        self.log("=" * 60)
        self.log("STARTING DISCORD SELFBOT")
        self.log("=" * 60)

        try:
            # Add BASE_DIR to path for imports
            if str(BASE_DIR) not in sys.path:
                sys.path.insert(0, str(BASE_DIR))

            from core.selfbot_runner import SelfbotRunner
            self.selfbot_runner = SelfbotRunner()
            
            # This will run the selfbot (blocking)
            result = await self.selfbot_runner.run()
            return result == 0

        except Exception as e:
            self.log(f"ERROR starting selfbot: {e}")
            logger.exception("Selfbot startup error")
            return False

    def shutdown(self, *args):
        """Graceful shutdown handler"""
        if not self.running:
            return

        self.log("")
        self.log("=" * 60)
        self.log("SHUTTING DOWN...")
        self.log("=" * 60)

        self.running = False

        # Stop selfbot
        if self.selfbot_runner:
            self.log("Stopping selfbot...")
            # We don't need to await here as we're in a signal handler usually
            # or about to exit the main loop

        # Stop bridge process
        if self.bridge_process:
            self.log("Stopping bridge server...")
            try:
                self.bridge_process.terminate()
                self.bridge_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.bridge_process.kill()
            except Exception as e:
                logger.error(f"Process terminate error: {e}")

        self.shutdown_event.set()

    async def run(self):
        """Main run loop - starts both services"""
        self.log("=" * 60)
        self.log("DISCORD SELFBOT + HERMES BRIDGE")
        self.log("Combined Runner (Dynamic Paths)")
        self.log("=" * 60)

        self.running = True

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.shutdown)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        # Step 1: Start Bridge Server
        if not await self.start_bridge():
            self.log("Failed to start bridge server. Exiting.")
            return 1

        # Step 2: Start streaming bridge output in a background thread
        bridge_output_thread = threading.Thread(
            target=self._stream_bridge_output_sync, daemon=True
        )
        bridge_output_thread.start()

        # Step 3: Start Selfbot
        selfbot_success = await self.start_selfbot()

        # Cleanup
        self.shutdown()
        return 0 if selfbot_success else 1


def main():
    """Entry point"""
    runner = CombinedRunner()
    try:
        return asyncio.run(runner.run())
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
