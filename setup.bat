@echo off
rem One-time setup: creates .venv and installs everything Clip Downloader 2.0 needs.
cd /d "%~dp0"
echo Creating virtual environment...
py -3 -m venv .venv 2>nul || python -m venv .venv
if not exist .venv\Scripts\python.exe (
  echo Could not create .venv. Install Python 3.12 from python.org and try again.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
where ffmpeg >nul 2>nul
if errorlevel 1 (
  if not exist bin\ffmpeg.exe (
    echo NOTE: ffmpeg was not found. Put ffmpeg.exe and ffprobe.exe in a "bin" folder here, or add ffmpeg to PATH.
  )
)
echo.
echo Done. Double-click "Clip Downloader.bat" to start.
pause
