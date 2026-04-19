@echo off
REM Release script for Inebotten Discord Bot
REM Usage: create-release.bat [version]
REM Example: create-release.bat v2.0.0

setlocal enabledelayedexpansion

if "%1"=="" (
    set VERSION=v2.0.0
) else (
    set VERSION=%1
)

echo ==========================================
echo Creating release: %VERSION%
echo ==========================================
echo.

REM Check if git is clean
for /f "delims=" %%i in ('git status --porcelain') do (
    set UNCOMMITTED=1
)

if defined UNCOMMITTED (
    echo WARNING: You have uncommitted changes
    echo    Please commit or stash them before creating a release
    set /p CONTINUE="Continue anyway? (y/N) "
    if /i not "!CONTINUE!"=="y" exit /b 1
)

REM Check if tag already exists
git rev-parse %VERSION% >nul 2>&1
if %errorlevel% equ 0 (
    echo WARNING: Tag %VERSION% already exists
    set /p RECREATE="Delete and recreate? (y/N) "
    if /i "!RECREATE!"=="y" (
        git tag -d %VERSION%
        git push origin ":refs/tags/%VERSION%" 2>nul
    ) else (
        exit /b 1
    )
)

REM Get current branch
for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%i
echo Current branch: %BRANCH%
echo.

REM Show recent commits
echo Recent commits:
git log --oneline -5
echo.

REM Confirm
set /p CONFIRM="Create release %VERSION% on branch %BRANCH%? (y/N) "
if /i not "!CONFIRM!"=="y" exit /b 1

REM Create and push tag
echo.
echo Creating tag...
git tag -a %VERSION% -m "Release %VERSION%"

echo Pushing tag to GitHub...
git push origin %VERSION%

echo.
echo ==========================================
echo Release %VERSION% created!
echo ==========================================
echo.
echo GitHub Actions will now:
echo   1. Build macOS app
echo   2. Build Windows app
echo   3. Create GitHub release
echo   4. Upload executables
echo.
echo Monitor progress at:
echo   https://github.com/Reedtrullz/inebotten-discord/actions
echo.
echo Release will be available at:
echo   https://github.com/Reedtrullz/inebotten-discord/releases/tag/%VERSION%
echo.

endlocal
