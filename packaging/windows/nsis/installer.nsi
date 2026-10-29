; Clippr setup — per-user install with Start menu + Desktop shortcuts and an uninstaller.
Unicode true
!define APPNAME "Clippr"
!define APPVER "2.3.0"
!define UNKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Clippr"
!include "MUI2.nsh"
!include "FileFunc.nsh"

Name "${APPNAME}"
OutFile "Clippr-Setup-${APPVER}.exe"
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"
InstallDirRegKey HKCU "${UNKEY}" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APPNAME} ${APPVER}"
VIProductVersion "2.3.0.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "FileVersion" "${APPVER}"
VIAddVersionKey "ProductVersion" "${APPVER}"
VIAddVersionKey "LegalCopyright" "James"

!define MUI_ICON "app.ico"
!define MUI_UNICON "app.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "wizard.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "wizard.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Install ${APPNAME}"
!define MUI_WELCOMEPAGE_TEXT "Clip and download YouTube, Instagram and X videos, save audio from those and SoundCloud as MP3, convert video, audio and pictures, resize and compress files.$\r$\n$\r$\nEverything it needs (Python, Qt and ffmpeg) is included. It installs just for you, so no administrator rights are needed.$\r$\n$\r$\nClick Next to continue."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPNAME}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME} now"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "!${APPNAME}" SecApp
  SectionIn RO
  ; an older copy may still be running
  nsExec::Exec 'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Clippr*"'
  ; replace the older "Clip Downloader" install (same app before the rename)
  ReadRegStr $0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipDownloader" "InstallLocation"
  StrCmp $0 "" +7
    nsExec::Exec 'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Clip Downloader*"'
    ExecWait '"$0\Uninstall.exe" /S _?=$0'
    RMDir /r "$0"
    Delete "$DESKTOP\Clip Downloader.lnk"
    Delete "$SMPROGRAMS\Clip Downloader.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipDownloader"
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  File "..\stage\${APPNAME}.exe"
  File /r "..\stage\runtime"
  File /r "..\stage\app"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortCut "$SMPROGRAMS\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.exe" "" "$INSTDIR\app\assets\app.ico" 0
  WriteRegStr HKCU "${UNKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNKEY}" "DisplayVersion" "${APPVER}"
  WriteRegStr HKCU "${UNKEY}" "Publisher" "James"
  WriteRegStr HKCU "${UNKEY}" "DisplayIcon" "$INSTDIR\app\assets\app.ico"
  WriteRegStr HKCU "${UNKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNKEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNKEY}" "EstimatedSize" 324176
SectionEnd

Section "Desktop shortcut" SecDesktop
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPNAME}.exe" "" "$INSTDIR\app\assets\app.ico" 0
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecApp} "The app with everything it needs, plus a Start menu entry."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "Put a ${APPNAME} shortcut on your Desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  nsExec::Exec 'taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq Clippr*"'
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}.lnk"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\app"
  Delete "$INSTDIR\${APPNAME}.exe"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNKEY}"
SectionEnd
