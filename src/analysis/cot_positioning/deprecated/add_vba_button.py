"""
Add VBA macro and button to Excel report using win32com
This script requires:
- Windows OS
- Microsoft Excel installed
- pywin32 package (pip install pywin32)
"""
import os
import sys
import time

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

try:
    import win32com.client
except ImportError:
    print("[ERROR] pywin32 package not found!")
    print("\nPlease install it with:")
    print("  pip install pywin32")
    sys.exit(1)

print("="*80)
print("ADDING VBA MACRO AND BUTTON TO COT REPORT")
print("="*80)

# File paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
INPUT_FILE = os.path.join(PROJECT_ROOT, 'tools', 'CoT_Positioning_Report.xlsx')
OUTPUT_FILE = os.path.join(PROJECT_ROOT, 'tools', 'CoT_Positioning_Report.xlsm')

# Convert to Windows path if running in WSL
if INPUT_FILE.startswith('/mnt/'):
    # Convert WSL path to Windows path
    INPUT_FILE = INPUT_FILE.replace('/mnt/c/', 'C:\\').replace('/', '\\')
    OUTPUT_FILE = OUTPUT_FILE.replace('/mnt/c/', 'C:\\').replace('/', '\\')

print(f"\nInput file:  {INPUT_FILE}")
print(f"Output file: {OUTPUT_FILE}")

if not os.path.exists(INPUT_FILE):
    print(f"\n[ERROR] Excel file not found: {INPUT_FILE}")
    sys.exit(1)

# VBA code for the update macro
vba_code = '''Private Sub Workbook_Open()
    ' Clear log on new session
    On Error Resume Next
    Dim logSheet As Worksheet
    Set logSheet = ThisWorkbook.Sheets("UpdateLog")
    If Not logSheet Is Nothing Then
        logSheet.Cells.Clear
        logSheet.Range("A1").Value = "Session Started: " & Now()
        logSheet.Range("A2").Value = String(80, "=")
    End If
    On Error GoTo 0
End Sub

Private Sub LogMessage(msg As String)
    ' Log message to UpdateLog sheet with timestamp
    On Error Resume Next
    Dim logSheet As Worksheet
    Set logSheet = ThisWorkbook.Sheets("UpdateLog")

    If logSheet Is Nothing Then
        ' Create log sheet if it doesn't exist
        Set logSheet = ThisWorkbook.Sheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        logSheet.Name = "UpdateLog"
        logSheet.Tab.Color = RGB(255, 255, 0) ' Yellow tab
    End If

    Dim nextRow As Long
    nextRow = logSheet.Cells(logSheet.Rows.Count, 1).End(xlUp).Row + 1

    logSheet.Cells(nextRow, 1).Value = Now()
    logSheet.Cells(nextRow, 2).Value = msg

    ' Auto-fit columns
    logSheet.Columns("A:B").AutoFit

    On Error GoTo 0
End Sub

Sub UpdateCoTReport()
    '
    ' Update CoT Report Macro
    ' Reads lookback period from Dashboard!B4 and regenerates the report
    ' Keeps Excel open and automatically reopens the updated file
    '

    Dim lookbackYears As Integer
    Dim projectPath As String
    Dim pythonScript As String
    Dim shellCommand As String
    Dim ws As Worksheet
    Dim wsh As Object
    Dim workbookPath As String
    Dim returnCode As Integer

    On Error GoTo ErrorHandler

    LogMessage "=== UPDATE STARTED ==="
    LogMessage "Button clicked by user"

    ' Disable screen updating for better UX
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False

    ' Get lookback period from Dashboard
    LogMessage "Reading lookback period from Dashboard!B4"
    Set ws = ThisWorkbook.Sheets("Dashboard")
    On Error Resume Next
    lookbackYears = ws.Range("B4").Value
    On Error GoTo ErrorHandler

    LogMessage "Lookback period: " & lookbackYears & " years"

    ' Validate lookback period
    If lookbackYears < 1 Or lookbackYears > 10 Then
        LogMessage "ERROR: Invalid lookback period: " & lookbackYears
        MsgBox "Invalid lookback period in cell B4!" & vbCrLf & _
               "Please enter a value between 1 and 10 years.", _
               vbExclamation, "Invalid Input"
        Application.ScreenUpdating = True
        Application.DisplayAlerts = True
        Exit Sub
    End If

    LogMessage "Validation passed"

    ' Confirm with user
    Dim msg As String
    msg = "This will update the report with a " & lookbackYears & "-year lookback period." & vbCrLf & vbCrLf & _
          "This may take 1-2 minutes. Please wait..." & vbCrLf & vbCrLf & _
          "The file will close and reopen automatically when done." & vbCrLf & vbCrLf & _
          "Continue?"

    LogMessage "Waiting for user confirmation"
    Dim answer As VbMsgBoxResult
    answer = MsgBox(msg, vbQuestion + vbYesNo, "Update CoT Report")

    If answer = vbNo Then
        LogMessage "User cancelled update"
        Application.ScreenUpdating = True
        Application.DisplayAlerts = True
        Exit Sub
    End If

    LogMessage "User confirmed - proceeding with update"

    ' Store the workbook path before closing
    workbookPath = ThisWorkbook.FullName
    LogMessage "Workbook path: " & workbookPath

    ' Get project root path (workbook is in tools/ folder)
    projectPath = ThisWorkbook.Path
    projectPath = Left(projectPath, InStrRev(projectPath, Application.PathSeparator) - 1)
    LogMessage "Project root: " & projectPath

    ' Path to Python script
    pythonScript = projectPath & Application.PathSeparator & "src" & Application.PathSeparator & _
                   "analysis" & Application.PathSeparator & "cot_positioning" & Application.PathSeparator & _
                   "report_generator.py"
    LogMessage "Python script: " & pythonScript

    ' Build shell command with output redirection to capture Python output
    Dim logFilePath As String
    logFilePath = projectPath & Application.PathSeparator & "tools" & Application.PathSeparator & "python_output.log"

    shellCommand = "cmd.exe /c ""cd /d """ & projectPath & """ && " & _
                   "python """ & pythonScript & """ --lookback " & lookbackYears & " > """ & logFilePath & """ 2>&1"""
    LogMessage "Command: " & shellCommand
    LogMessage "Python output will be saved to: " & logFilePath

    ' Save and close the workbook before regenerating
    LogMessage "Saving workbook"
    ThisWorkbook.Save
    LogMessage "Closing workbook"
    ThisWorkbook.Close SaveChanges:=False

    ' Create WScript.Shell object to run command and wait
    LogMessage "Creating WScript.Shell object"
    Set wsh = CreateObject("WScript.Shell")

    ' Run the Python script and wait for completion
    ' 0 = hidden window, True = wait for completion
    LogMessage "Executing Python script (this may take 1-2 minutes)"
    returnCode = wsh.Run(shellCommand, 0, True)
    LogMessage "Python script completed with return code: " & returnCode

    ' Read Python output log and add to UpdateLog
    LogMessage "--- PYTHON OUTPUT START ---"
    On Error Resume Next
    Dim fso As Object, pythonLog As Object, line As String
    Set fso = CreateObject("Scripting.FileSystemObject")
    If fso.FileExists(logFilePath) Then
        Set pythonLog = fso.OpenTextFile(logFilePath, 1)  ' 1 = ForReading
        Do While Not pythonLog.AtEndOfStream
            line = pythonLog.ReadLine
            LogMessage line
        Loop
        pythonLog.Close
    Else
        LogMessage "ERROR: Python output log file not found!"
    End If
    On Error GoTo ErrorHandler
    LogMessage "--- PYTHON OUTPUT END ---"

    ' Check if script ran successfully
    If returnCode = 0 Then
        LogMessage "SUCCESS: Report generation completed"
        ' Reopen the updated workbook
        LogMessage "Reopening workbook: " & workbookPath
        Application.Workbooks.Open workbookPath
        LogMessage "Workbook reopened successfully"
        MsgBox "Report updated successfully!" & vbCrLf & vbCrLf & _
               "Lookback period: " & lookbackYears & " years" & vbCrLf & vbCrLf & _
               "Check the UpdateLog sheet for details.", _
               vbInformation, "Update Complete"
    Else
        LogMessage "ERROR: Python script failed with code " & returnCode
        MsgBox "Update failed! Return code: " & returnCode & vbCrLf & vbCrLf & _
               "Please check if Python is installed and in PATH." & vbCrLf & vbCrLf & _
               "See UpdateLog sheet for details.", _
               vbCritical, "Update Failed"
    End If

    ' Clean up
    Set wsh = Nothing
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True

    LogMessage "=== UPDATE COMPLETED ==="
    Exit Sub

ErrorHandler:
    LogMessage "FATAL ERROR: " & Err.Description & " (Error " & Err.Number & ")"
    MsgBox "An error occurred: " & Err.Description & vbCrLf & vbCrLf & _
           "See UpdateLog sheet for details.", _
           vbCritical, "Error"
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True

End Sub
'''

try:
    print("\nStarting Excel application...")
    excel = win32com.client.Dispatch("Excel.Application")
    excel.Visible = False  # Run in background
    excel.DisplayAlerts = False

    print(f"Opening workbook: {INPUT_FILE}")
    wb = excel.Workbooks.Open(INPUT_FILE)

    # Add VBA module
    print("Adding VBA module...")
    vba_module = wb.VBProject.VBComponents.Add(1)  # 1 = vbext_ct_StdModule
    vba_module.Name = "CoTUpdateModule"
    vba_module.CodeModule.AddFromString(vba_code)
    print("[OK] VBA module added")

    # Get Dashboard sheet
    print("Accessing Dashboard sheet...")
    dashboard = wb.Sheets("Dashboard")

    # Create or clear UpdateLog sheet
    print("Setting up UpdateLog sheet...")
    log_sheet = None

    # Check if UpdateLog sheet already exists
    for i in range(1, wb.Sheets.Count + 1):
        if wb.Sheets(i).Name == "UpdateLog":
            log_sheet = wb.Sheets(i)
            log_sheet.Cells.Clear()
            print("[OK] UpdateLog sheet found and cleared")
            break

    # Create new sheet if it doesn't exist
    if log_sheet is None:
        log_sheet = wb.Sheets.Add(After=wb.Sheets(wb.Sheets.Count))
        log_sheet.Name = "UpdateLog"
        print("[OK] UpdateLog sheet created")

    # Format the sheet
    try:
        log_sheet.Tab.ColorIndex = 6  # Yellow
        print("[OK] Tab color set")
    except Exception as e:
        print(f"[WARN] Could not set tab color: {e}")

    try:
        log_sheet.Range("A1").Value = "Session Started: " + time.strftime("%Y-%m-%d %H:%M:%S")
        log_sheet.Range("A2").Value = "=" * 80
        print("[OK] Header text added")
    except Exception as e:
        print(f"[WARN] Could not add header: {e}")

    try:
        log_sheet.Columns("A:A").ColumnWidth = 20
        log_sheet.Columns("B:B").ColumnWidth = 80
        print("[OK] Column widths set")
    except Exception as e:
        print(f"[WARN] Could not set column widths: {e}")

    print("[OK] UpdateLog sheet ready")

    # Remove existing buttons (to avoid duplicates)
    print("Checking for existing buttons...")
    try:
        for btn in dashboard.Buttons():
            if btn.Text == "Update Report":
                btn.Delete()
                print("[OK] Removed existing Update Report button")
    except:
        pass  # No buttons exist

    # Add button
    # Position button at top of sheet (above the data table)
    button_left = 10
    button_top = 10
    button_width = 120
    button_height = 30

    print("Adding Update button...")
    try:
        button = dashboard.Buttons().Add(button_left, button_top, button_width, button_height)
        print("[OK] Button shape created")
    except Exception as e:
        print(f"[ERROR] Could not create button: {e}")
        raise

    try:
        button.OnAction = "UpdateCoTReport"
        print("[OK] Macro linked")
    except Exception as e:
        print(f"[ERROR] Could not link macro: {e}")
        raise

    try:
        button.Characters.Text = "Update Report"
        print("[OK] Button text set")
    except Exception as e:
        print(f"[ERROR] Could not set button text: {e}")
        raise

    try:
        # Format button
        button.Font.Name = "Calibri"
        button.Font.Size = 11
        button.Font.Bold = True
        print("[OK] Button formatted")
    except Exception as e:
        print(f"[WARN] Could not format button: {e}")

    print("[OK] Button added and linked to macro")

    # Save as macro-enabled workbook
    print(f"\nSaving as macro-enabled workbook: {OUTPUT_FILE}")

    # Delete output file if it exists
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)
        time.sleep(0.5)  # Give Windows time to release the file

    # Save as .xlsm (macro-enabled)
    # FileFormat 52 = xlOpenXMLWorkbookMacroEnabled (.xlsm)
    wb.SaveAs(OUTPUT_FILE, FileFormat=52)
    print("[OK] File saved")

    # Close workbook
    wb.Close(SaveChanges=False)
    excel.Quit()

    print("\n" + "="*80)
    print("SUCCESS!")
    print("="*80)
    print(f"\n[OK] Created: {OUTPUT_FILE}")
    print("\nThe Excel file now has:")
    print("  - VBA macro: UpdateCoTReport()")
    print("  - Update button on Dashboard sheet (top-left corner)")
    print("  - UpdateLog sheet (yellow tab) - logs cleared on each session")
    print("\nHow to use:")
    print("  1. Open the .xlsm file")
    print("  2. Enable macros when prompted")
    print("  3. Change lookback period in cell B4")
    print("  4. Click 'Update Report' button")
    print("  5. File will close and reopen with updated data")
    print("  6. Check UpdateLog sheet for execution details")
    print("\nTroubleshooting:")
    print("  - If update fails, check UpdateLog sheet for error messages")
    print("  - Log is cleared automatically when you open the workbook")
    print("="*80)

except Exception as e:
    print(f"\n[ERROR] {str(e)}")
    print("\nPossible solutions:")
    print("  1. Make sure Excel is installed")
    print("  2. Close Excel if it's running")
    print("  3. Install pywin32: pip install pywin32")
    print("  4. Enable VBA access in Excel:")
    print("     File > Options > Trust Center > Trust Center Settings")
    print("     > Macro Settings > Trust access to VBA project object model")
    try:
        excel.Quit()
    except:
        pass
    sys.exit(1)
