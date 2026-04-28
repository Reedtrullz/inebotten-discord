#!/bin/bash
# Quick setup script for building Inebotten macOS app

set -e

echo "=========================================="
echo "Inebotten macOS App Quick Setup"
echo "=========================================="
echo ""

# Check if we're in the right directory
if [ ! -f "mac_app/launcher.py" ]; then
    echo "Error: Please run this script from the inebotten-discord directory"
    echo "Usage: ./mac_app/setup.sh"
    exit 1
fi

# Check Python
echo "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "✓ Python found: $PYTHON_VERSION"
else
    echo "✗ Python 3 not found"
    echo "Please install Python 3.12+ from https://www.python.org/downloads/"
    exit 1
fi

# Check Python version
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 12 ]); then
    echo "✗ Python 3.12+ required, found $PYTHON_VERSION"
    exit 1
fi

echo "✓ Python version OK"
echo ""

# Install dependencies
echo "Installing dependencies..."
pip3 install -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# Install PyInstaller
echo "Installing PyInstaller..."
pip3 install pyinstaller
echo "✓ PyInstaller installed"
echo ""

# Build the app
echo "Building the app..."
cd mac_app
python3 build.py

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Your app is ready at: dist/Inebotten.app"
echo ""
echo "To install:"
echo "  mv dist/Inebotten.app /Applications/"
echo ""
echo "To run:"
echo "  open dist/Inebotten.app"
echo ""
