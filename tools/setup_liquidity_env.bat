@echo off
echo ========================================
echo   Setting up Liquidity Dashboard Environment
echo ========================================
echo.

cd /d "%~dp0.."

REM Check if venv already exists
if exist "venv_liquidity" (
    echo Virtual environment already exists.
    echo To recreate, delete the venv_liquidity folder first.
    pause
    exit /b
)

echo Creating virtual environment...
python -m venv venv_liquidity

echo.
echo Activating environment...
call venv_liquidity\Scripts\activate.bat

echo.
echo Installing required packages...
pip install --upgrade pip
pip install streamlit>=1.28.0
pip install pandas>=2.0.0
pip install plotly>=5.17.0
pip install fredapi>=0.5.0
pip install numpy>=1.24.0

echo.
echo ========================================
echo   Setup Complete!
echo ========================================
echo.
echo To run the dashboard, use:
echo   tools\launch_liquidity_dashboard.bat
echo.
pause
