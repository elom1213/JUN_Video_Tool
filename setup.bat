@echo off
rem JUN Video Tool - one-shot dependency setup (PLAN 13.6)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 bootstrap.py %*
) else (
    python bootstrap.py %*
)
echo.
pause
