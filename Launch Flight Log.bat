@echo off
setlocal
cd /d "%~dp0"
title Flight log

REM Double-click does not install Python. This file only uses a Python
REM that is already on PATH, then creates a local environment on first run.

set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found.
  echo Install Python 3.11 or newer from https://www.python.org/downloads/windows/
  echo and turn on "Add python.exe to PATH" in the installer.
  echo Then double-click this file again.
  echo.
  echo This launcher cannot install Python for you.
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: creating a local environment and installing flightlog.
  echo This needs an internet connection once, for NumPy and Matplotlib.
  echo.
  %PY% -m venv .venv
  if errorlevel 1 goto :venvfail
  ".venv\Scripts\python.exe" -m pip install -e .
  if errorlevel 1 goto :pipfail
  echo.
)

echo Opening the flight log in your browser.
echo Leave this window open while you use the page. Closing it stops the page.
echo.
".venv\Scripts\python.exe" -m flightlog ui
if errorlevel 1 goto :runfail
exit /b 0

:venvfail
echo.
echo Could not create the local environment.
echo If Windows asked you to install python3-venv or the py launcher failed,
echo reinstall Python 3.11+ with "Add python.exe to PATH" and try again.
echo.
pause
exit /b 1

:pipfail
echo.
echo The install did not finish. Read the message above.
echo The first run needs an internet connection so NumPy and Matplotlib can download.
echo.
pause
exit /b 1

:runfail
echo.
echo The page did not start. Read the message above.
echo.
pause
exit /b 1
