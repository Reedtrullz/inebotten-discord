#!/usr/bin/env python3
"""Thin Windows entry point; install requirements/desktop.lock before building."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_desktop import main


if __name__ == "__main__":
    raise SystemExit(main(["windows", *sys.argv[1:]]))
