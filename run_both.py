#!/usr/bin/env python3
"""
Discord Selfbot + Hermes Bridge Combined Runner
Starts both services together with proper coordination

Usage:
    python3 run_both.py          # Start both bridge + selfbot
    python3 selfbot_runner.py    # Selfbot only (bridge must be running)
    python3 hermes_bridge_server.py  # Bridge only

This will:
1. Start the Hermes Bridge Server (connects to LM Studio)
2. Wait for bridge to be ready (checks /health endpoint)
3. Start the Discord Selfbot
4. Stream output from both services (prefixed [BRIDGE] or [SELFBOT])
5. Handle graceful shutdown on Ctrl+C (stops both services)

Requirements:
    - LM Studio running on Windows host (or fallback mode works without it)
    - Valid Discord token in .env file
    - Python dependencies: discord.py aiohttp requests
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
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)

    async def start_bridge(self):
        """Start the Hermes Bridge Server as a subprocess"""
        self.log("")
        self.log("=" * 60)
        self.log("STARTING HERMES BRIDGE SERVER")
        self.log("=" * 60)

        # Check if bridge is already running
        try:
            response = requests.get(BRIDGE_HEALTH_URL, timeout=2)
            if response.status_code == 200:
                data = response.json()
                lm_status = data.get("lm_studio", "unknown")
                self.log(f"✓ Bridge already running! LM Studio: {lm_status}")
                self.log("  (Using existing bridge instance)")
                return True
        except Exception as e:
            print(f"[RUNNER] Bridge check error: {e}")

        # Get the path to the bridge server
        bridge_script = Path(__file__).parent / "ai" / "hermes_bridge_server.py"

        if not bridge_script.exists():
            self.log(f"ERROR: Bridge script not found: {bridge_script}")
            return False

        # Start bridge in subprocess with unbuffered output
        self.log(f"Starting bridge: {bridge_script.name}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self.bridge_process = subprocess.Popen(
            [sys.executable, "-u", str(bridge_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env,
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
            except requests.exceptions.ConnectionError:
                pass
            except Exception:
                pass

            # Check if bridge process died
            if self.bridge_process.poll() is not None:
                self.log(
                    f"ERROR: Bridge process exited with code {self.bridge_process.poll()}"
                )
                # Read any error output
                remaining_output = self.bridge_process.stdout.read()
                if remaining_output:
                    self.log(f"Bridge output: {remaining_output}")
                return False

            await asyncio.sleep(0.5)

        self.log(f"ERROR: Bridge failed to start within {BRIDGE_READY_TIMEOUT}s")
        return False

    def _stream_bridge_output_sync(self):
        """Stream bridge output in a separate thread"""
        if not self.bridge_process or not self.bridge_process.stdout:
            return

        try:
            while self.running and self.bridge_process.poll() is None:
                line = self.bridge_process.stdout.readline()
                if line:
                    print(f"[BRIDGE] {line.rstrip()}", flush=True)
                else:
                    time.sleep(0.1)
        except Exception as e:
            print(f"[BRIDGE OUTPUT ERROR] {e}", flush=True)

    async def start_selfbot(self):
        """Start the Discord Selfbot"""
        self.log("")
        self.log("=" * 60)
        self.log("STARTING DISCORD SELFBOT")
        self.log("=" * 60)

        # Import and run the selfbot
        try:
            # Add current directory to path for imports
            sys.path.insert(0, str(Path(__file__).parent))

            # Import the selfbot runner class
            from core.selfbot_runner import SelfbotRunner

            self.selfbot_runner = SelfbotRunner()

            # Run the selfbot
            self.log("Initializing selfbot...")
            result = await self.selfbot_runner.run()

            return result == 0

        except ImportError as e:
            self.log(f"ERROR: Could not import selfbot modules: {e}")
            self.log("Make sure all dependencies are installed:")
            self.log("  pip3 install discord.py aiohttp requests")
            return False
        except Exception as e:
            self.log(f"ERROR starting selfbot: {e}")
            import traceback

            traceback.print_exc()
            return False

    def shutdown(self):
        """Graceful shutdown handler"""
        if not self.running:
            return

        self.log("")
        self.log("=" * 60)
        self.log("SHUTTING DOWN...")
        self.log("=" * 60)

        self.running = False

        # Stop selfbot first
        if self.selfbot_runner:
            self.log("Stopping selfbot...")
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.selfbot_runner.shutdown())
            except Exception as e:
                print(f"[RUNNER] Shutdown error: {e}")

        # Stop bridge process
        if self.bridge_process:
            self.log("Stopping bridge server...")
            try:
                self.bridge_process.terminate()
                # Give it a moment to exit gracefully
                time.sleep(0.5)
                if self.bridge_process.poll() is None:
                    self.bridge_process.kill()
                    self.bridge_process.wait()
            except Exception as e:
                print(f"[RUNNER] Process terminate error: {e}")

        self.shutdown_event.set()

    async def run(self):
        """Main run loop - starts both services"""
        self.log("=" * 60)
        self.log("DISCORD SELFBOT + HERMES BRIDGE")
        self.log("Combined Runner")
        self.log("=" * 60)
        self.log("")
        self.log("This will start:")
        self.log("  1. Hermes Bridge Server (connects to LM Studio)")
        self.log("  2. Discord Selfbot (@inebotten)")
        self.log("")
        self.log("Press Ctrl+C to stop both services")
        self.log("=" * 60)

        self.running = True

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.shutdown)

        # Step 1: Start Bridge Server
        if not await self.start_bridge():
            self.log("Failed to start bridge server. Exiting.")
            return 1

        # Step 2: Start streaming bridge output in a background thread
        bridge_output_thread = threading.Thread(
            target=self._stream_bridge_output_sync, daemon=True
        )
        bridge_output_thread.start()

        # Small delay to let bridge output start
        await asyncio.sleep(0.5)

        # Step 3: Start Selfbot (this blocks until shutdown)
        selfbot_success = await self.start_selfbot()

        # Cleanup
        self.shutdown()

        # Wait for bridge output thread to finish
        bridge_output_thread.join(timeout=2)

        self.log("")
        self.log("=" * 60)
        self.log("ALL SERVICES STOPPED")
        self.log("=" * 60)

        return 0 if selfbot_success else 1


def main():
    """Entry point"""
    runner = CombinedRunner()

    try:
        return asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\n[MAIN] Interrupted by user")
        return 0
    except Exception as e:
        print(f"\n[MAIN] Fatal error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
