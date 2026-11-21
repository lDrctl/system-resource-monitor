@echo off
setlocal
title PC Condition
pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist "dashboard.py" goto missing_files
if not exist "requirements.txt" goto missing_files

set "PC_CONDITION_PYTHON=.venv\Scripts\python.exe"
if exist "%PC_CONDITION_PYTHON%" goto prepare
set "PC_CONDITION_PYTHON=syswatch\.venv\Scripts\python.exe"
if exist "%PC_CONDITION_PYTHON%" goto prepare

set "PC_CONDITION_PYTHON=.venv\Scripts\python.exe"
echo Preparing the Python environment...
py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto python_command
py -3 -m venv .venv
if errorlevel 1 goto failed
goto prepare

:python_command
python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv .venv
if errorlevel 1 goto failed

:prepare
echo Checking required packages. The first setup may take a few minutes...
"%PC_CONDITION_PYTHON%" -m pip --disable-pip-version-check install -q -r requirements.txt
if errorlevel 1 goto failed

echo Starting PC Condition...
echo Keep this window open. Press Ctrl+C to stop.
"%PC_CONDITION_PYTHON%" -m streamlit run dashboard.py --server.address 127.0.0.1 --server.headless false --browser.gatherUsageStats false
if errorlevel 1 goto failed
popd
exit /b 0

:missing_files
echo Extract the ZIP first. Keep this file next to dashboard.py and requirements.txt.
goto failed

:missing_python
echo Install Python 3.10 or later, then run this file again.
goto failed

:failed
echo PC Condition could not start. Check the message above.
pause
popd
exit /b 1
