# Builds a standalone Windows app into dist\Clip Downloader\ (and a zip of it).
# Usage (PowerShell, from this folder):  .\build.ps1      For the installer use make_installer.bat instead.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run setup.bat first." }
& $py -m pip show pyinstaller *> $null
if ($LASTEXITCODE) { & $py -m pip install pyinstaller -q }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name "Clip Downloader" `
    --icon "assets\app.ico" `
    --add-data "assets;assets" `
    --add-data "clipdl\qml_ui\qml;clipdl\qml_ui\qml" `
    --collect-submodules qframelesswindow `
    --collect-all pillow_heif `
    --collect-all pymupdf `
    --exclude-module tkinter `
    run.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$dist = "dist\Clip Downloader"
# Qt Quick's QML modules (the new interface needs them next to the app)
$qmlSrc = & $py -c "import PySide6,os; print(os.path.join(os.path.dirname(PySide6.__file__), 'qml'))"
$internal = if (Test-Path "$dist\_internal") { "$dist\_internal" } else { $dist }
foreach ($m in "QtQuick", "QtQml", "QtMultimedia") {
    $from = Join-Path $qmlSrc $m
    $to = Join-Path $internal "PySide6\qml\$m"
    if ((Test-Path $from) -and -not (Test-Path $to)) {
        New-Item -ItemType Directory -Force (Split-Path $to) | Out-Null
        Copy-Item $from $to -Recurse -Force
        Write-Host "Bundled QML module $m"
    }
}
New-Item -ItemType Directory -Force "$dist\bin" | Out-Null
foreach ($tool in "ffmpeg", "ffprobe") {
    $src = if (Test-Path "bin\$tool.exe") { "bin\$tool.exe" } else { (Get-Command $tool -ErrorAction SilentlyContinue).Source }
    if ($src) { Copy-Item $src "$dist\bin\$tool.exe" -Force; Write-Host "Bundled $tool from $src" }
    else { Write-Warning "$tool not found - the build will need ffmpeg on PATH" }
}
Compress-Archive -Path $dist -DestinationPath "dist\Clip Downloader.zip" -Force
Write-Host "Built: $dist  (zip: dist\Clip Downloader.zip)"
