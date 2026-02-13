@echo off
REM Launch CoT Positioning Dashboard - Streamlit App

echo ================================================================================
echo COT POSITIONING DASHBOARD
echo ================================================================================
echo.
echo Starting Streamlit dashboard...
echo.
echo The app will open in your browser automatically.
echo Press Ctrl+C to stop the server when done.
echo.
echo ================================================================================
echo.

cd /d "%~dp0.."
streamlit run src/analysis/cot_positioning/streamlit_app.py

pause
