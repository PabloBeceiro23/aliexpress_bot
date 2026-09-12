@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Falta la instalacion. Ejecuta install_windows.ps1 primero.
  pause
  exit /b 1
)
set LOCAL_PROFILE_DIR=%~dp0aliexpress_profile
set LOCAL_HEADLESS=0
.venv\Scripts\python.exe run_local.py
