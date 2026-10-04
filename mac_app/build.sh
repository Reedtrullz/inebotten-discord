#!/bin/bash
set -euo pipefail

# Requires requirements/desktop.lock in the active Python environment.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/build_desktop.py" macos "$@"
