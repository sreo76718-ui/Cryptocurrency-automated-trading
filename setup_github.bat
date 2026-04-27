@echo off
REM ============================================================
REM setup_github.bat  -  First-time GitHub setup (run once)
REM
REM Before running:
REM   1. Create an empty repo at https://github.com/new (no README)
REM   2. Edit REPO_URL below to your repo URL
REM ============================================================

set REPO_URL=https://github.com/sreo76718-ui/Cryptocurrency-automated-trading.git

cd /d "%~dp0"

echo === Initializing git ===
git init
git branch -M main

echo === Setting remote ===
git remote add origin %REPO_URL%

echo === First commit ===
git add .
git commit -m "initial commit: trading_bot setup"

echo === Pushing to GitHub ===
git push -u origin main

echo.
echo === Done! ===
echo Next: Go to your GitHub repo
echo   Settings ^> Secrets and variables ^> Actions
echo   Add secret:  DISCORD_WEBHOOK_URL
echo.
pause
