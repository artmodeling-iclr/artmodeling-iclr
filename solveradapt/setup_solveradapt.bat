@echo off
setlocal
cd /d "%~dp0"

py -3.11 -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 was not found. Install 64-bit Python 3.11 and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  py -3.11 -m venv ".venv"
  if errorlevel 1 (
    echo Could not create the local virtual environment.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 (
  echo Package installation failed. Check the connection and try again.
  pause
  exit /b 1
)

echo SolverAdapt dependencies are ready. Run run_solveradapt.bat next.
pause
