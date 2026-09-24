@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Ruleaza mai intai Instaleaza.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" start.py
if errorlevel 1 pause
