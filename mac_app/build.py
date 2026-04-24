#!/usr/bin/env python3
"""
Build script for Inebotten macOS executable
Creates a standalone .app bundle for M1 Mac
"""

import os
import sys
import subprocess
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    print("Checking dependencies...")
    
    # Check PyInstaller
    try:
        import PyInstaller
        print("✓ PyInstaller is installed")
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("✓ PyInstaller installed")
    
    # Check tkinter
    try:
        import tkinter
        print("✓ tkinter is available")
    except ImportError:
        print("✗ tkinter is not available")
        print("  tkinter should be included with Python on macOS")
        return False
    
    return True

def build_app():
    """Build the macOS app using PyInstaller"""
    print("\n" + "="*60)
    print("Building Inebotten macOS App")
    print("="*60 + "\n")
    
    # Get script directory
    script_dir = Path(__file__).parent.parent
    launcher_script = script_dir / "mac_app" / "launcher.py"
    
    if not launcher_script.exists():
        print(f"Error: Launcher script not found: {launcher_script}")
        return False
    
    # PyInstaller spec
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

a = Analysis(
    ['{launcher_script}'],
    pathex=[],
    binaries=[],
    datas=[
        ('ai', 'ai'),
        ('cal_system', 'cal_system'),
        ('core', 'core'),
        ('features', 'features'),
        ('memory', 'memory'),
        ('utils', 'utils'),
        ('docs', 'docs'),
    ],
    hiddenimports=[
        'discord',
        'aiohttp',
        'python-dateutil',
        'simpleeval',
        'dotenv',
        'keyring',
        'cryptography',
        'zoneinfo',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Inebotten',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Inebotten',
)

app = BUNDLE(
    coll,
    name='Inebotten.app',
    icon=None,
    bundle_identifier='com.inebotten.discordbot',
    info_plist={{
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'CFBundleShortVersionString': '2.0',
        'CFBundleVersion': '2.0.0',
        'NSRequiresAquaSystemAppearance': 'False',
    }},
)
"""
    
    # Write spec file
    spec_file = script_dir / "mac_app" / "Inebotten.spec"
    with open(spec_file, "w") as f:
        f.write(spec_content)
    
    print(f"Created spec file: {spec_file}")
    
    # Run PyInstaller
    print("\nBuilding with PyInstaller...")
    print("This may take a few minutes...\n")
    
    try:
        subprocess.check_call([
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            str(spec_file),
            "--noconfirm"
        ])
        
        print("\n" + "="*60)
        print("✓ Build successful!")
        print("="*60)
        print(f"\nApp location: {script_dir / 'dist' / 'Inebotten.app'}")
        print("\nTo run the app:")
        print(f"  open {script_dir / 'dist' / 'Inebotten.app'}")
        print("\nOr drag it to your Applications folder")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n✗ Build failed with error code {e.returncode}")
        return False
    except Exception as e:
        print(f"\n✗ Build failed: {e}")
        return False

def main():
    """Main entry point"""
    print("Inebotten macOS App Builder")
    print("="*60)
    
    # Check dependencies
    if not check_dependencies():
        print("\n✗ Missing required dependencies")
        sys.exit(1)
    
    # Build app
    if build_app():
        print("\n✓ Build complete!")
        sys.exit(0)
    else:
        print("\n✗ Build failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
