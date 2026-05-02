@echo off
chcp 65001 > nul
cd /d C:\Users\reo\Desktop\trading_bot

echo [1/4] Removing index.lock...
if exist .git\index.lock del /f .git\index.lock

echo [2/4] Staging all files...
git add -A

echo [3/4] Committing...
git -c user.email="sreo76718@gmail.com" -c user.name="reo" commit -m "feat: migrate to Cowork, disable GitHub Actions schedule, update logs and code"

echo [4/4] Pushing to GitHub...
git push origin main

echo.
echo === Done ===
pause
