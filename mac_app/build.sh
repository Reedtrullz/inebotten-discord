#!/bin/bash

# Build script for Inebotten Discord Bot - macOS
# Creates a standalone .app bundle using PyInstaller

set -e

echo "=========================================="
echo "Building Inebotten macOS App"
echo "=========================================="
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    echo "   Install Python 3.10+ from https://www.python.org/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✅ Found Python $PYTHON_VERSION"

# Check if PyInstaller is installed
if ! python3 -c "import PyInstaller" &> /dev/null; then
    echo "⚠️  PyInstaller not found, installing..."
    pip3 install pyinstaller
fi

# Check if launcher.py exists
if [ ! -f "launcher.py" ]; then
    echo "❌ Error: launcher.py not found"
    echo "   Make sure you're in the mac_app directory"
    exit 1
fi

echo "✅ Found launcher.py"
echo ""

# Build the app
echo "🔨 Building app with PyInstaller..."
pyinstaller \
    --name="Inebotten" \
    --onefile \
    --windowed \
    --icon=../assets/icon.icns \
    --add-data="../ai:ai" \
    --add-data="../cal_system:cal_system" \
    --add-data="../core:core" \
    --add-data="../features:features" \
    --add-data="../memory:memory" \
    --add-data="../utils:utils" \
    --add-data="../docs:docs" \
    --hidden-import=ai \
    --hidden-import=cal_system \
    --hidden-import=core \
    --hidden-import=features \
    --hidden-import=memory \
    --hidden-import=utils \
    --hidden-import=docs \
    launcher.py

echo ""
echo "✅ Build complete!"
echo ""

# Create .app bundle
echo "📦 Creating .app bundle..."
APP_NAME="Inebotten.app"
APP_PATH="dist/$APP_NAME"

# Remove existing app if it exists
if [ -d "$APP_PATH" ]; then
    echo "   Removing existing $APP_NAME..."
    rm -rf "$APP_PATH"
fi

# Create app structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Create Info.plist
cat > "$APP_PATH/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>Inebotten</string>
    <key>CFBundleIdentifier</key>
    <string>com.inebotten.discord</string>
    <key>CFBundleName</key>
    <string>Inebotten</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>2.0.0</string>
    <key>CFBundleVersion</key>
    <string>2.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.12</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Copy executable
cp dist/Inebotten "$APP_PATH/Contents/MacOS/"

# Make executable
chmod +x "$APP_PATH/Contents/MacOS/Inebotten"

# Copy icon if it exists
if [ -f "../assets/icon.icns" ]; then
    cp ../assets/icon.icns "$APP_PATH/Contents/Resources/"
fi

echo "✅ Created $APP_NAME"
echo ""

# Final output
echo "=========================================="
echo "✅ Build successful!"
echo "=========================================="
echo ""
echo "App location: $APP_PATH"
echo ""
echo "To run the app:"
echo "  open $APP_PATH"
echo ""
echo "To create a distributable zip:"
echo "  cd dist"
echo "  zip -r Inebotten-macos.zip Inebotten.app"
echo ""
