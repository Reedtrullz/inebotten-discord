@echo off
REM Quick setup script for building Inebotten Windows executable

echo ==========================================
echo Inebotten Windows App Quick Setup
echo ==========================================
echo.

REM Check if we're in the right directory
if not exist "windows_app\launcher.py" (
    echo Error: Please run this script from the inebotten-discord directory
    echo Usage: windows_app\setup.bat
    exit /b 1
)

REM Check Python
echo Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found
    echo Please install Python 3.12+ from https://www.python.org/downloads/
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python found: %PYTHON_VERSION%
echo.

REM Check Python version
python -c "import sys; exit(0 if sys.version_info.major >= 3 and sys.version_info.minor >= 12 else 1)" >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.12+ required
    echo Current version: %PYTHON_VERSION%
    exit /b 1
)

echo [OK] Python version OK
echo.

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    exit /b 1
)
echo [OK] Dependencies installed
echo.

REM Install PyInstaller
echo Installing PyInstaller...
pip install pyinstaller
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install PyInstaller
    exit /b
)
echo [OK] PyInstaller installed
echo.

REM Build the app
echo Building the app...
cd windows_app
python build.py
if %errorlevel% neq 0 (
    echo [ERROR] Build failed
    exit /b 1
)

echo.
echo ==========================================
echo Setup complete!
echo ==========================================
echo.
echo Your executable is ready at: dist\Inebotten.exe
echo.
echo To run it:
echo   dist\Inebotten.exe
echo.
echo Or create a shortcut on your desktop
echo.

pause
