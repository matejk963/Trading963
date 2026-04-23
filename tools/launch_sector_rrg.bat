@echo off
echo ========================================
echo   Sector RRG - Relative Rotation Graph
echo ========================================
echo.

cd /d "%~dp0.."

REM Try venv first, fall back to conda
if exist "venv_liquidity\Scripts\activate.bat" (
    call venv_liquidity\Scripts\activate.bat
) else (
    echo No venv found, using system Python...
)

echo Starting Sector RRG dashboard...
echo.

streamlit run src/analysis/sector_rrg/streamlit_app.py --server.port 8503

pause
