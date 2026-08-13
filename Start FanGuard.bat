@echo off
:: FanGuard Launcher - Run as Administrator
:: Double-click this to start FanGuard

cd /d "%~dp0"

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo Checking dependencies...
python -m pip install wmi pystray pillow --quiet

:: Launch FanGuard (it will self-elevate to Admin)
echo Starting FanGuard...
pythonw fan_guard.py

if %errorlevel% neq 0 (
    echo Failed to start. Running in console mode for debugging...
    python fan_guard.py
    pause
)
