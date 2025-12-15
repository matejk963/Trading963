# Deprecated Excel VBA Scripts

These scripts were used for the old Excel-based approach with VBA macros.

**Status:** DEPRECATED - No longer maintained

**Replacement:** Use the Streamlit dashboard instead (`streamlit_app.py`)

## Old Files

- `add_vba_button.py` - Added VBA macro and button to Excel using win32com
- `add_vba_macro.py` - Generated VBA code text file for manual setup

## Why Deprecated?

The Excel VBA approach had several issues:
- ❌ Complex setup (VBA security settings, pywin32 dependencies)
- ❌ Windows-only (COM automation)
- ❌ Unicode encoding issues
- ❌ Difficult error handling and debugging
- ❌ Manual macro setup required
- ❌ Static Excel charts

## New Approach

The Streamlit dashboard (`streamlit_app.py`) provides:
- ✅ Web-based (works on all platforms)
- ✅ Interactive Plotly charts
- ✅ Real-time updates with sliders
- ✅ Easy error handling and logging
- ✅ No VBA or Excel required
- ✅ Simple one-command launch

## Migration

If you were using the Excel reports, switch to:

```bash
# Launch dashboard
streamlit run src/analysis/cot_positioning/streamlit_app.py

# Or double-click
tools/launch_cot_dashboard.bat
```

## Files Cleanup

To remove old Excel files:
```cmd
tools/cleanup_old_excel_files.bat
```

---

These files are kept for reference only.
