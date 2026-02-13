#!/bin/bash
# Launch CoT Positioning Dashboard - Streamlit App

echo "================================================================================"
echo "COT POSITIONING DASHBOARD"
echo "================================================================================"
echo ""
echo "Starting Streamlit dashboard..."
echo ""
echo "The app will open in your browser automatically."
echo "Press Ctrl+C to stop the server when done."
echo ""
echo "================================================================================"
echo ""

# Get the directory where this script is located and navigate to parent
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

streamlit run src/analysis/cot_positioning/streamlit_app.py

echo ""
read -p "Press enter to continue..."
