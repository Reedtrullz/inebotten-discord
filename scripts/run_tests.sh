#!/bin/bash
# Inebotten Automated Test Runner
# Run this script to test all bot functionality

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=========================================="
echo "INEBOTTEN AUTOMATED TEST SUITE"
echo "=========================================="
echo ""
echo "Running pytest suite..."
echo ""

python3 -m pytest tests/test_comprehensive.py -q

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ All tests passed! The bot is ready to use."
else
    echo "❌ Some tests failed. Please check the output above."
fi

exit $exit_code
