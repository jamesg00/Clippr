@echo off
rem Builds the Windows installer (dist\installer\Clip-Downloader-Setup-<version>.exe).
rem Add /install to also install it (Desktop + Start menu shortcuts).
cd /d "%~dp0"
set EXTRA=
if /i "%~1"=="/install" set EXTRA=-Install
powershell -NoProfile -ExecutionPolicy Bypass -File "packaging\windows\make_installer.ps1" %EXTRA%
if errorlevel 1 (
  echo.
  echo Build failed - see the messages above.
)
pause
