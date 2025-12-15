"""
CoT Report Updater
Reads the lookback period from existing Excel file and regenerates the report
"""
import os
import sys
import subprocess
from openpyxl import load_workbook

# Get project root directory (go up 3 levels: cot_positioning -> analysis -> src -> root)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
EXCEL_FILE = os.path.join(PROJECT_ROOT, 'tools', 'CoT_Positioning_Report.xlsx')
GENERATOR_SCRIPT = os.path.join(PROJECT_ROOT, 'src', 'analysis', 'cot_positioning', 'report_generator.py')

print("="*80)
print("COT REPORT UPDATER")
print("="*80)

# Check if Excel file exists
if not os.path.exists(EXCEL_FILE):
    print(f"\n❌ Excel file not found: {EXCEL_FILE}")
    print("Please run the generator first to create the initial report.")
    sys.exit(1)

# Read lookback period from Excel
try:
    print(f"\nReading lookback period from: {EXCEL_FILE}")
    wb = load_workbook(EXCEL_FILE, data_only=True)
    dashboard = wb['Dashboard']
    lookback_years = dashboard['B4'].value

    if lookback_years is None or not isinstance(lookback_years, (int, float)):
        print(f"⚠ Invalid lookback period in B4: {lookback_years}")
        print("Using default: 3 years")
        lookback_years = 3
    else:
        lookback_years = int(lookback_years)

    wb.close()
    print(f"✓ Lookback period: {lookback_years} years")

except Exception as e:
    print(f"❌ Error reading Excel file: {e}")
    print("Using default lookback period: 3 years")
    lookback_years = 3

# Regenerate report
print(f"\n{'='*80}")
print(f"REGENERATING REPORT WITH {lookback_years} YEAR LOOKBACK")
print(f"{'='*80}\n")

try:
    # Call the generator script with lookback parameter
    result = subprocess.run(
        [sys.executable, GENERATOR_SCRIPT, '--lookback', str(lookback_years)],
        cwd=PROJECT_ROOT,
        capture_output=False,
        text=True
    )

    if result.returncode == 0:
        print(f"\n{'='*80}")
        print("✓ REPORT UPDATED SUCCESSFULLY!")
        print(f"{'='*80}")
        print(f"File: {EXCEL_FILE}")
        print(f"Lookback Period: {lookback_years} years")
    else:
        print(f"\n❌ Error updating report (exit code: {result.returncode})")
        sys.exit(1)

except Exception as e:
    print(f"\n❌ Error running generator: {e}")
    sys.exit(1)
