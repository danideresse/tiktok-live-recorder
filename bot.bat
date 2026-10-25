@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Run python -m venv .venv
    pause
    exit /b 1
)

echo [*] Starting TikTok Live Recorder Telegram Bot...
.venv\Scripts\python.exe src\bot.py
pause
