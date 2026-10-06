#!/usr/bin/env python3
"""Generate or check the repository command reference from one catalogue."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.command_registry import command_reference


def main():
    target = Path(__file__).resolve().parents[1] / 'docs/COMMANDS.md'
    expected = command_reference()
    if sys.argv[1:] == ['--check']:
        return 0 if target.exists() and target.read_text() == expected else 1
    if sys.argv[1:]:
        return 2
    target.write_text(expected)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
