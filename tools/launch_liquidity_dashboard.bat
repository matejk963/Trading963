@echo off
echo ========================================
echo   Global Liquidity Monitoring Dashboard
echo ========================================
echo.

cd /d "%~dp0.."

REM Check if virtual environment exists
if not exist "venv_liquidity\Scripts\activate.bat" (
    echo Virtual environment not found!
    echo Run setup_liquidity_env.bat first.
    pause
    exit /b
)

REM Activate virtual environment
call venv_liquidity\Scripts\activate.bat

echo Starting Streamlit dashboard...
echo.

streamlit run src/analysis/liquidity_monitoring/streamlit_app.py

pause
