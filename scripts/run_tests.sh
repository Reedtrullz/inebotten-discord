#!/bin/bash
# Inebotten Automated Test Runner
# Run this script to test all bot functionality

cd "$(dirname "$0")"

echo "=========================================="
echo "INEBOTTEN AUTOMATED TEST SUITE"
echo "=========================================="
echo ""
echo "Running comprehensive tests..."
echo ""

python3 test_selfbot_comprehensive.py

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ All tests passed! The bot is ready to use."
else
    echo "❌ Some tests failed. Please check the output above."
fi

exit $exit_code
