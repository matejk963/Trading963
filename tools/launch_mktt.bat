@echo off
title MKTT - Trading Terminal
echo ========================================
echo   MKTT - Matej Krajcovic Trading Tool
echo ========================================
echo.

cd /d "%~dp0..\src\mktt"

REM Install Flask if missing
python -c "import flask" 2>nul
if errorlevel 1 (
    echo Installing Flask...
    python -m pip install flask yfinance pandas -q
)

echo Starting MKTT on http://localhost:5001 ...
echo Browser will open in 3 seconds...
echo.

REM Open browser after a delay (in background)
start /B cmd /C "timeout /t 3 /nobreak >nul & start http://localhost:5001"

REM Start Flask (blocks here)
python app.py

pause
