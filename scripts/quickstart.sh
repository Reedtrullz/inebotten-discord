#!/bin/bash
#
# Quick Start Script for Discord Selfbot
# Sets up environment and runs tests
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  DISCORD SELFBOT - QUICK START"
echo "============================================================"
echo ""

# Check if .env exists and load it
if [ -f .env ]; then
    echo "[1/4] Loading environment from .env..."
    set -a
    source .env
    set +a
    echo "  ✓ Environment loaded"
else
    echo "[1/4] No .env file found"
    echo "  ⚠ Using environment variables or defaults"
fi

# Install dependencies
echo ""
echo "[2/4] Installing dependencies..."
python3 setup.py

# Run tests
echo ""
echo "[3/4] Running test suite..."
python3 test_selfbot.py
TEST_RESULT=$?

if [ $TEST_RESULT -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo "  ✅ SELFBOT READY"
    echo "============================================================"
    echo ""
    echo "To start BOTH bridge server + selfbot together:"
    echo "  python3 run_both.py"
    echo ""
    echo "Or start them separately:"
    echo "  Terminal 1: python3 hermes_bridge_server.py"
    echo "  Terminal 2: python3 selfbot_runner.py"
    echo ""
else
    echo ""
    echo "============================================================"
    echo "  ❌ TESTS FAILED"
    echo "============================================================"
    echo ""
    echo "Please fix the issues above before starting the selfbot."
    echo ""
    exit 1
fi
