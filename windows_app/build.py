"""
Build script for Inebotten Discord Bot - Windows
Creates a standalone .exe using PyInstaller
"""

import os
import sys
import subprocess
import shutil

def check_python():
    """Check if Python is installed"""
    print("[OK] Found Python", sys.version.split()[0])
    return True

def check_pyinstaller():
    """Check if PyInstaller is installed"""
    try:
        import PyInstaller
        print("[OK] Found PyInstaller")
        return True
    except ImportError:
        print("[WARN] PyInstaller not found, installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("[OK] PyInstaller installed")
        return True

def check_launcher():
    """Check if launcher.py exists"""
    if not os.path.exists("launcher.py"):
        print("[ERROR] launcher.py not found")
        print("   Make sure you're in the windows_app directory")
        return False
    print("[OK] Found launcher.py")
    return True

def build_app():
    """Build the Windows executable"""
    print("\n[INFO] Building Windows executable with PyInstaller...")

    # PyInstaller command
    cmd = [
        "pyinstaller",
        "--name=Inebotten",
        "--onefile",
        "--windowed",
        "--add-data=../ai;ai",
        "--add-data=../cal_system;cal_system",
        "--add-data=../core;core",
        "--add-data=../features;features",
        "--add-data=../memory;memory",
        "--add-data=../utils;utils",
        "--add-data=../docs;docs",
        "--hidden-import=ai",
        "--hidden-import=cal_system",
        "--hidden-import=core",
        "--hidden-import=features",
        "--hidden-import=memory",
        "--hidden-import=utils",
        "--hidden-import=docs",
        "--hidden-import=win32api",
        "--hidden-import=win32con",
        "--hidden-import=win32gui",
        "--hidden-import=win32file",
        "launcher.py"
    ]

    try:
        subprocess.run(cmd, check=True)
        print("\n[OK] Build complete!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Build failed: {e}")
        return False

def main():
    """Main build function"""
    print("=" * 50)
    print("Building Inebotten Windows App")
    print("=" * 50)
    print()

    # Check prerequisites
    if not check_python():
        sys.exit(1)

    if not check_pyinstaller():
        sys.exit(1)

    if not check_launcher():
        sys.exit(1)

    # Build the app
    if not build_app():
        sys.exit(1)

    # Final output
    print()
    print("=" * 50)
    print("[OK] Build successful!")
    print("=" * 50)
    print()
    print("Executable location: dist\\Inebotten.exe")
    print()
    print("To run the app:")
    print("  dist\\Inebotten.exe")
    print()

if __name__ == "__main__":
    main()
