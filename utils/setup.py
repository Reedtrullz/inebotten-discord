#!/usr/bin/env python3
"""Compatibility entry point for the retired dependency installer."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    print("The legacy dependency installer is retired; it no longer installs packages.")
    print("From the project directory, prepare an isolated environment with:")
    print("  python3 -m venv .venv312")
    if sys.platform == "win32":
        print(r"  .venv312\Scripts\python.exe -m pip install -r requirements.txt")
    else:
        print("  .venv312/bin/python -m pip install -r requirements.txt")
    print(f"Project: {project_root}")
    print("Then run: python setup.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
