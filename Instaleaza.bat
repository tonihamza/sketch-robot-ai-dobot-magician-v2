@echo off
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 (
  echo Instaleaza Python 3.12 cu Tcl/Tk, apoi ruleaza din nou.
  pause
  exit /b 1
)
if exist "wheels\numpy-2.2.6-cp312-cp312-win_amd64.whl" (
  ".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements.txt
) else (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
pause
