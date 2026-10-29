@echo off
rem Builds the installer and installs Clip Downloader (Desktop + Start menu shortcuts) in one go.
call "%~dp0..\..\make_installer.bat" /install
