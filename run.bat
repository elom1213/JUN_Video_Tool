@echo off
rem JUN Video Tool - launcher. Uses .venv if bootstrap created one.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" launch.py
    goto :eof
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 launch.py
) else (
    start "" pythonw launch.py
)
