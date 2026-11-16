@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Run setup_solveradapt.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "api_usd.py"
if errorlevel 1 (
  echo SolverAdapt stopped with an error. Read the message above.
  pause
  exit /b 1
)
