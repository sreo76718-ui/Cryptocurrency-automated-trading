@echo off
REM ============================================================
REM push_data.bat
REM Commits and pushes bot logs/state to GitHub.
REM Schedule via Windows Task Scheduler at 22:50 JST daily.
REM ============================================================

cd /d "%~dp0"

echo [push_data] %DATE% %TIME% - Pushing data...

git add data\logs\ data\state\ config.yml
git diff --cached --quiet
if %errorlevel% equ 0 (
    echo [push_data] No changes. Skipping.
    exit /b 0
)

git commit -m "data: %DATE% %TIME% auto-commit"
git push origin main

if %errorlevel% equ 0 (
    echo [push_data] Push complete. GitHub Actions will send the report at 23:00 JST.
) else (
    echo [push_data] ERROR: Push failed. Check your git config.
    exit /b 1
)
