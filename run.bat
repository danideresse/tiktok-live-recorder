@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Virtual environment not found. Run python -m venv .venv
    pause
    exit /b 1
)

if "%~1"=="" (
    .venv\Scripts\python.exe src\main.py -h
) else (
    .venv\Scripts\python.exe src\main.py %*
)
