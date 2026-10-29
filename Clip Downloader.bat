@echo off
rem Starts Clip Downloader 2.0 without a console window. Pass --solid to start with glass off.
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe run.py %*
) else (
  echo First run setup.bat to install the requirements.
  pause
)
