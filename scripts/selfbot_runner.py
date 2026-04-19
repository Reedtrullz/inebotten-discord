#!/usr/bin/env python3
"""
Discord Selfbot Runner - Main Entry Point (Root Wrapper)

This is a thin wrapper that delegates to core.selfbot_runner.
Run this from the project root, or use run_both.py to start everything.
"""

import sys
from pathlib import Path

# Ensure project root is in path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# Import and run the actual implementation from core/
from core.selfbot_runner import main

if __name__ == "__main__":
    sys.exit(main())
