; Tiny launcher: "Clippr.exe" starts the app with its bundled Python (no console window).
Unicode true
!include "FileFunc.nsh"
Name "Clippr"
OutFile "Clippr.exe"
Icon "app.ico"
RequestExecutionLevel user
SilentInstall silent
SetCompressor /SOLID lzma
VIProductVersion "2.3.0.0"
VIAddVersionKey "ProductName" "Clippr"
VIAddVersionKey "FileDescription" "Clippr"
VIAddVersionKey "FileVersion" "2.3.0"
VIAddVersionKey "ProductVersion" "2.3.0"
VIAddVersionKey "LegalCopyright" "James"
Section
  ${GetParameters} $R0
  SetOutPath "$EXEDIR\app"
  IfFileExists "$EXEDIR\runtime\pythonw.exe" +3
    MessageBox MB_ICONSTOP "Clippr is missing files. Please reinstall it."
    Quit
  Exec '"$EXEDIR\runtime\pythonw.exe" "$EXEDIR\app\run.py" $R0'
SectionEnd
